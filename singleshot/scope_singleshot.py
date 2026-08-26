import os
import sys
import time
import struct
import math
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pyvisa
from arduino_thermal import ThermalController

def parse_preamble(pre_raw):
    recv = pre_raw[pre_raw.find(b'#') + 11:]
    vdiv = struct.unpack('f', recv[0x9c:0x9c+4])[0]
    offset = struct.unpack('f', recv[0xa0:0xa0+4])[0]
    code_per_div = struct.unpack('f', recv[0xa4:0xa4+4])[0]
    interval = struct.unpack('f', recv[0xb0:0xb0+4])[0]
    delay = struct.unpack('d', recv[0xb4:0xb4+8])[0]
    probe = struct.unpack('f', recv[0x148:0x148+4])[0]
    adc_bit = struct.unpack('h', recv[0xac:0xac+2])[0]
    points = struct.unpack('i', recv[116:120])[0] 
    return {'vdiv': vdiv * probe, 'offset': offset * probe, 'code_per_div': code_per_div,
            'interval': interval, 'delay': delay, 'probe': probe, 'adc_bit': adc_bit, 'points': points}

def acquire(acquisition_config):
    if not acquisition_config:
        raise ValueError("ERRORE CRITICO: Devi fornire il dizionario 'acquisition_config'!")

    OSCILLOSCOPE_IP = acquisition_config['OSCILLOSCOPE_IP']
    V_DIV_CH1       = acquisition_config['V_DIV_CH1']
    V_DIV_CH2       = acquisition_config['V_DIV_CH2']
    T_DIV           = acquisition_config['T_DIV']
    PROBE_ATT       = acquisition_config['PROBE_ATT']
    TRIG_LEVEL      = acquisition_config['TRIG_LEVEL']
    TRIG_CH         = acquisition_config['TRIG_CH']
    ARDUINO_PORT       = acquisition_config.get('ARDUINO_PORT', '/dev/ttyACM0')
    LASER_WAIT_SEC     = acquisition_config.get('LASER_WAIT_SEC', 5.0)
    
    # === BUDGET TERMICO DINAMICO ===
    KAPTON_PWM = acquisition_config.get('KAPTON_PWM', 1.0)
    MAX_JOULES = acquisition_config.get('MAX_JOULES', 140.0) # <--- ORA LO PRENDE DAL NOTEBOOK!
    POTENZA_MAX_W = 14.0
    potenza_erogata = KAPTON_PWM * POTENZA_MAX_W
    
    tempo_riscaldamento = MAX_JOULES / potenza_erogata if potenza_erogata > 0 else 0.0

    print("\n" + "="*50)
    print("      CONTROLLO SICUREZZA TERMODINAMICA")
    print("="*50)
    print(f"  Potenza Impostata: {KAPTON_PWM*100:.0f}% -> {potenza_erogata:.1f} W")
    print(f"  Budget Sicurezza : {MAX_JOULES} Joule")
    print(f"  Tempo Max Kapton : {tempo_riscaldamento:.2f} secondi")
    print("="*50 + "\n")

    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    tz_rome = ZoneInfo("Europe/Rome")
    now = datetime.now(tz_rome)
    date_str = now.strftime("%Y%m%d")         
    time_str = now.strftime("%H%M")           
    date_time_str = f"{date_str}_{time_str}_singleshot"  
    base_path = os.path.join(SCRIPT_DIR, "acquisitions_singleshot", date_str, date_time_str)
    os.makedirs(base_path, exist_ok=True)

    controller = ThermalController(port=ARDUINO_PORT)

    print("Connessione all'oscilloscopio in corso...")
    rm = pyvisa.ResourceManager('@py') 
    try:
        scope = rm.open_resource(f'TCPIP0::{OSCILLOSCOPE_IP}::inst0::INSTR')
        scope.timeout = 30000 
        scope.chunk_size = 20 * 1024 * 1024 
    except Exception as e:
        print(f"Connection error: {e}")
        controller.spegni_tutto()
        return None

    print("Connected to:", scope.query("*IDN?").strip())
    print("Configuring parameters...")
    scope.write(f"CHAN1:PROB {PROBE_ATT}")
    scope.write(f"CHAN2:PROB {PROBE_ATT}")
    scope.write(f"CHAN1:SCAL {V_DIV_CH1}")
    scope.write(f"CHAN2:SCAL {V_DIV_CH2}")
    scope.write(f"TIM:SCAL {T_DIV}")
    
    trigger_delay = 4 * T_DIV
    scope.write(f"TIM:DEL {trigger_delay}")
    scope.write(f"TRIG:EDGE:SOUR {TRIG_CH}")
    scope.write(f"TRIG:EDGE:LEVel {TRIG_LEVEL}")
    scope.write("ACQuire:MMANagement AUTO") 

    print(f"Accensione Laser... Attesa {LASER_WAIT_SEC}s per assestamento.")
    controller.accendi_laser()
    time.sleep(LASER_WAIT_SEC)

    total_window = T_DIV * 10 
    post_trigger_window = T_DIV * 9  
    print(f"Starting single acquisition. Total time window: {total_window} s.")
    scope.write("TRIG:MODE SINGle")
    
    last_status = ""
    triggered = False
    start_trigger_time = 0
    
    kapton_armed = False
    kapton_is_on = False
    kapton_start_abs = 0.0
    kapton_stop_abs = 0.0
    
    while True:
        status = scope.query("TRIG:STAT?").strip()
        
        # 1. SCOPE PRONTO: Accendiamo il Kapton!
        if status == "Ready" and not kapton_armed:
            print(f"Oscilloscopio ARMATO: Accensione Kapton al {KAPTON_PWM*100:.0f}%!")
            controller.imposta_kapton(KAPTON_PWM)
            kapton_start_abs = time.time()
            kapton_armed = True
            kapton_is_on = True
            
        # 2. WATCHDOG TEMPORALE: Se superiamo il limite in Joule, spegniamo forzatamente!
        if kapton_is_on:
            if (time.time() - kapton_start_abs) >= tempo_riscaldamento:
                print(f"\n[!!! SICUREZZA !!!] Raggiunti i {MAX_JOULES} Joule! Spegnimento Kapton forzato.")
                controller.imposta_kapton(0.0)
                kapton_stop_abs = time.time()
                kapton_is_on = False
            
        if status != last_status and not triggered:
            print(f"Oscilloscope status: {status}")
            last_status = status
            
        if "Trig" in status:
            if not triggered:
                triggered = True
                start_trigger_time = time.time() 
                print(f"Trigger detected! Acquiring remaining {post_trigger_window} seconds...")
            
            elapsed = time.time() - start_trigger_time
            progress = elapsed / post_trigger_window
            if progress > 1.0: progress = 1.0
                
            bar_length = 40
            filled = int(bar_length * progress)
            bar = '█' * filled + '░' * (bar_length - filled)
            sys.stdout.write(f"\rAcquiring: [{bar}] {progress * 100:.1f}%")
            sys.stdout.flush()
            
        if "Stop" in status:
            if triggered:
                sys.stdout.write(f"\rAcquiring: [{'█' * 40}] 100.0%\n")
                sys.stdout.flush()
            elif last_status == "Ready":
                print(f"Acquiring: [{'█' * 40}] 100.0%")
            print("Acquisition completed!")
            break
            
        time.sleep(0.2) 

    # Spegniamo hardware a prescindere
    print("Spegnimento totale hardware per evitare surriscaldamento plastico...")
    controller.spegni_tutto()
    if kapton_is_on:
        kapton_stop_abs = time.time()

    print("Starting download of binary chunks from Oscilloscope...")

    # Logica tempi relativi al trigger per il grafico
    t_start_rel = (kapton_start_abs - start_trigger_time) if start_trigger_time > 0 else 0
    t_stop_rel = (kapton_stop_abs - start_trigger_time) if start_trigger_time > 0 else (time.time() - start_trigger_time)

    kapton_log = {
        "pwm": KAPTON_PWM,
        "t_start_s": t_start_rel,
        "t_stop_s": t_stop_rel
    }

    channels = ["C1", "C2"]
    preambles = {}  

    for ch in channels:
        print(f"\n--- Analyzing channel {ch} ---")
        scope.write(f"WAV:SOUR {ch}")
        scope.write("WAV:PRE?")
        pre_raw = scope.read_raw()
        preamble = parse_preamble(pre_raw)
        preambles[ch] = preamble  
        
        if preamble['adc_bit'] > 8: scope.write("WAV:WIDT WORD")
        else: scope.write("WAV:WIDT BYTE")
            
        total_points = preamble['points']
        try: max_points = int(float(scope.query("WAV:MAXP?").strip()))
        except: max_points = total_points 
            
        if total_points > max_points: scope.write(f"WAV:POIN {max_points}")
            
        chunks = math.ceil(total_points / max_points)
        full_bin_data = bytearray() 
        
        for i in range(chunks):
            start_idx = i * max_points
            progress = (i + 1) / chunks
            bar_length = 40
            filled = int(bar_length * progress)
            bar = '█' * filled + '░' * (bar_length - filled)
            sys.stdout.write(f"\r  -> Downloading: [{bar}] {progress * 100:.1f}% (Packet {i+1}/{chunks})")
            sys.stdout.flush()
            
            scope.write(f"WAV:STAR {start_idx}")
            scope.write("WAV:DATA?")
            wav_raw = scope.read_raw()
            idx = wav_raw.find(b'#')
            if idx != -1:
                digits_len = int(chr(wav_raw[idx+1]))
                header_len = 2 + digits_len
                full_bin_data.extend(wav_raw[idx + header_len : -2]) 
        
        print() 
        with open(os.path.join(base_path, f"{date_time_str}_data_{ch}.bin"), 'wb') as f:
            f.write(full_bin_data)
        
    meta_data = {
        "acquisition_config": acquisition_config,
        "preambles": preambles,
        "kapton_log": kapton_log
    }
    
    json_filename = os.path.join(base_path, f"{date_time_str}_meta.json")
    with open(json_filename, 'w') as f_json:
        json.dump(meta_data, f_json, indent=4)
    
    scope.close()
    print("Acquisition process finished successfully!")
    return base_path