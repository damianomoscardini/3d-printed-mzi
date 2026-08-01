import os
import sys
import time
import struct
import math
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pyvisa

def parse_preamble(pre_raw):
    """Extracts fundamental parameters from the Preamble binary block."""
    recv = pre_raw[pre_raw.find(b'#') + 11:]
    
    vdiv = struct.unpack('f', recv[0x9c:0x9c+4])[0]
    offset = struct.unpack('f', recv[0xa0:0xa0+4])[0]
    code_per_div = struct.unpack('f', recv[0xa4:0xa4+4])[0]
    interval = struct.unpack('f', recv[0xb0:0xb0+4])[0]
    delay = struct.unpack('d', recv[0xb4:0xb4+8])[0]
    probe = struct.unpack('f', recv[0x148:0x148+4])[0]
    adc_bit = struct.unpack('h', recv[0xac:0xac+2])[0]
    points = struct.unpack('i', recv[116:120])[0] 
    
    return {
        'vdiv': vdiv * probe,
        'offset': offset * probe,
        'code_per_div': code_per_div,
        'interval': interval,
        'delay': delay,
        'probe': probe,
        'adc_bit': adc_bit,
        'points': points
    }

def acquire(acquisition_config):
    """
    Connects to the oscilloscope, performs a single-shot acquisition, 
    and saves ONLY raw binary data and a comprehensive JSON metadata file.
    """
    if not acquisition_config:
        raise ValueError("ERRORE CRITICO: Devi fornire il dizionario 'acquisition_config'!")

    # Nessun default! Se manca una chiave nel Notebook, il codice andrà in crash (KeyError).
    OSCILLOSCOPE_IP = acquisition_config['OSCILLOSCOPE_IP']
    V_DIV_CH1       = acquisition_config['V_DIV_CH1']
    V_DIV_CH2       = acquisition_config['V_DIV_CH2']
    T_DIV           = acquisition_config['T_DIV']
    PROBE_ATT       = acquisition_config['PROBE_ATT']
    TRIG_LEVEL      = acquisition_config['TRIG_LEVEL']
    TRIG_CH         = acquisition_config['TRIG_CH']

    # ==========================================
    # FOLDER CREATION & TIMEZONE
    # ==========================================
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    # Impostazione rigorosa del fuso orario di Roma
    tz_rome = ZoneInfo("Europe/Rome")
    now = datetime.now(tz_rome)

    date_str = now.strftime("%Y%m%d")         
    time_str = now.strftime("%H%M")           
    # Aggiungiamo "_singleshot" come standard
    date_time_str = f"{date_str}_{time_str}_singleshot"  

    # Nuova cartella root per le acquisizioni singleshot
    base_path = os.path.join(SCRIPT_DIR, "acquisitions_singleshot", date_str, date_time_str)
    os.makedirs(base_path, exist_ok=True)

    rm = pyvisa.ResourceManager('@py') 
    
    try:
        scope = rm.open_resource(f'TCPIP0::{OSCILLOSCOPE_IP}::inst0::INSTR')
        scope.timeout = 30000 
        scope.chunk_size = 20 * 1024 * 1024 
    except Exception as e:
        print(f"Connection error: {e}")
        return None

    print("Connected to:", scope.query("*IDN?").strip())
    
    # -----------------------------------------------------
    # 1. OSCILLOSCOPE SETUP
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # 2. START SINGLE ACQUISITION
    # -----------------------------------------------------
    total_window = T_DIV * 10 
    post_trigger_window = T_DIV * 9  
    
    print(f"Starting single acquisition. Total time window: {total_window} s.")
    scope.write("TRIG:MODE SINGle")
    
    last_status = ""
    triggered = False
    start_trigger_time = 0
    
    while True:
        status = scope.query("TRIG:STAT?").strip()
        
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
            print("Acquisition completed! Starting download...")
            break
            
        time.sleep(0.2) 

    # -----------------------------------------------------
    # 3. CHUNK DATA READING AND RAW SAVING
    # -----------------------------------------------------
    channels = ["C1", "C2"]
    preambles = {}  

    for ch in channels:
        print(f"\n--- Analyzing channel {ch} ---")
        scope.write(f"WAV:SOUR {ch}")
        
        scope.write("WAV:PRE?")
        pre_raw = scope.read_raw()
        preamble = parse_preamble(pre_raw)
        preambles[ch] = preamble  
        
        if preamble['adc_bit'] > 8:
            scope.write("WAV:WIDT WORD")
        else:
            scope.write("WAV:WIDT BYTE")
            
        total_points = preamble['points']
        
        try:
            max_points = int(float(scope.query("WAV:MAXP?").strip()))
        except:
            max_points = total_points 
            
        print(f"  > Captured points in memory: {total_points}")
        print(f"  > LAN transfer limit per packet: {max_points}")
        
        if total_points > max_points:
            scope.write(f"WAV:POIN {max_points}")
            
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
                chunk_data = wav_raw[idx + header_len : -2]
                full_bin_data.extend(chunk_data) 
        
        print() 
        
        # Salvataggio con il nuovo naming standard
        bin_filename = os.path.join(base_path, f"{date_time_str}_data_{ch}.bin")
        with open(bin_filename, 'wb') as f:
            f.write(full_bin_data)
        
        print(f"Saved complete raw binary file (Total bytes: {len(full_bin_data)})")

    # === SALVATAGGIO METADATI JSON SUPER-INTEGRATO ===
    meta_data = {
        "acquisition_config": acquisition_config,
        "preambles": preambles
    }
    
    json_filename = os.path.join(base_path, f"{date_time_str}_meta.json")
    with open(json_filename, 'w') as f_json:
        json.dump(meta_data, f_json, indent=4)
    
    print(f"\nSaved integrated metadata file: {json_filename}")

    scope.close()
    print("Acquisition process finished successfully!")
    
    return base_path

if __name__ == '__main__':
    print("This is a module. Please import it into your notebook.")