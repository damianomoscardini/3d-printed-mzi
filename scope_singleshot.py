import os
# FORZA il backend grafico a livello di sistema operativo PRIMA di tutto!
os.environ['MPLBACKEND'] = 'TkAgg'

import csv
from datetime import datetime
import time
from zoneinfo import ZoneInfo
import pyvisa
import numpy as np
import matplotlib.pyplot as plt

# --- CONFIGURAZIONE PRINCIPALE ---
OSC_IP = '169.254.235.175'
TOTAL_TIME_S = 180          # Tempo totale desiderato dell'evento (s)
TARGET_CSV_POINTS = 20000     # Numero massimo di righe desiderate nel CSV finale

# Costante per Siglent Serie 800X HD (12-bit)
# I convertitori 12-bit mappano il voltaggio con altissima risoluzione.
# Se i Volt sul grafico risultano sballati di un fattore ~8, cambia in 409.6
ADC_CODE_PER_DIV = 3200.0 

def get_closest_tdiv(target_total_time):
    """Calcola il gradino Time/Div (1-2-5) per l'SDS824X HD (Griglia da 10 divisioni)"""
    target_tdiv = target_total_time / 10.0  
    
    multipliers = [1.0, 2.0, 5.0]
    decades = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0]
    
    valid_tdivs = [m * d for d in decades for m in multipliers]
    
    for tdiv in valid_tdivs:
        if tdiv >= target_tdiv:
            return tdiv
    return valid_tdivs[-1]

def main():
    # --- 1. GESTIONE TIMEZONE E NOMI CARTELLE ---
    tz_roma = ZoneInfo("Europe/Rome")
    ora_corrente = datetime.now(tz_roma)

    data_str = ora_corrente.strftime('%Y%m%d')
    ora_str = ora_corrente.strftime('%H%M')
    nome_base = f"{data_str}_{ora_str}_FAST"

    cartella_acquisizione = os.path.join("acquisitions", data_str, nome_base)
    os.makedirs(cartella_acquisizione, exist_ok=True)

    file_dati = os.path.join(cartella_acquisizione, f"{nome_base}.csv")
    file_setup = os.path.join(cartella_acquisizione, f"{nome_base}_setup.txt")
    file_grafico = os.path.join(cartella_acquisizione, f"{nome_base}_plot.png")

    # --- 2. CONNESSIONE PYVISA ---
    rm = pyvisa.ResourceManager('@py')
    resource_string = f"TCPIP0::{OSC_IP}::inst0::INSTR"

    print(f"Connessione a {resource_string}...")
    try:
        inst = rm.open_resource(resource_string)
        # Timeout a 20 secondi per consentire il download di 50 Megapunti
        inst.timeout = 20000 
    except Exception as e:
        print(f"Errore di connessione PyVISA: {e}")
        return

    idn = inst.query("*IDN?")
    print(f"Connesso a: {idn.strip()}")
    
    # --- 3. AUTO-SETUP MATEMATICO ---
    best_tdiv = get_closest_tdiv(TOTAL_TIME_S)
    actual_time = best_tdiv * 10.0 
    print(f"Richiesti {TOTAL_TIME_S}s. Impostato Time/Div a {best_tdiv} s/div (Tempo reale coperto: {actual_time}s)")
    
    settings_applied = []
    def apply_cmd(cmd):
        inst.write(cmd)
        settings_applied.append(cmd)

    apply_cmd(f"TDIV {best_tdiv}S") 
    # Sfruttiamo i 50 Megapunti massimi del SDS824X HD
    apply_cmd("MSIZ 50M") 
    # Entra in modalità Trigger Singolo
    apply_cmd("TRMD SINGLE")
    
    # --- 4. CREAZIONE FILE DI SETUP (PARTE INIZIALE) ---
    with open(file_setup, 'w', encoding='utf-8') as fs:
        fs.write("--- SETUP ESPERIMENTO MACH-ZEHNDER (TRANSIENTE VELOCE) ---\n")
        fs.write(f"Strumento: {idn.strip()}\n")
        fs.write(f"Inizio Sessione: {ora_corrente.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fs.write(f"Modalità Acquisizione: BULK BINARY DOWNLOAD (12-bit)\n")
        fs.write(f"Tempo Totale Richiesto: {TOTAL_TIME_S} sec (Coperto fisicamente: {actual_time} sec)\n")
        fs.write(f"Target punti CSV desiderati: {TARGET_CSV_POINTS}\n")
        fs.write("\n--- COMANDI SCPI INVIATI ---\n")
        for imp in settings_applied:
            fs.write(f"- {imp}\n")

    # --- 5. ATTESA DEL TRIGGER ---
    print("\n[⏳] Oscilloscopio ARMATO in SINGLE Trigger. In attesa dell'evento...")
    print("Fai avvenire la variazione (Premi Ctrl+C per annullare se non scatta).")
    
    try:
        while True:
            status = inst.query("SAST?").strip()
            if "Stop" in status:
                print("[!] EVENTO CATTURATO! L'oscilloscopio si è fermato.")
                break
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nAcquisizione annullata. Ripristino oscilloscopio in AUTO...")
        inst.write("TRMD AUTO")
        inst.close()
        return

    # --- 6. DOWNLOAD DATI IN BLOCCO (BULK TRANSFER) ---
    print("\nInizio scaricamento della forma d'onda grezza...")
    
    raw_vdiv = inst.query("C1:VDIV?")
    raw_ofst = inst.query("C1:OFST?")
    vdiv_ch1 = float(raw_vdiv.split(' ')[1].replace('V', ''))
    ofst_ch1 = float(raw_ofst.split(' ')[1].replace('V', ''))
    
    inst.write("C1:WF? DAT2")
    raw_bytes = inst.read_raw()
    
    header_idx = raw_bytes.find(b'#9')
    if header_idx != -1:
        data_len = int(raw_bytes[header_idx+2 : header_idx+11])
        wave_data = raw_bytes[header_idx+11 : header_idx+11+data_len]
        print(f"Scaricati {data_len/1000000:.2f} MB di dati grezzi.")
    else:
        print("Errore: Header binario '#9' non trovato.")
        return

    inst.write("TRMD AUTO")
    inst.close()

    # --- 7. DECODIFICA BINARIA VELOCE (NUMPY) ---
    print("Decodifica dati a 12-bit in Volt...")
    
    raw_adc = np.frombuffer(wave_data, dtype=np.int16)
    volts_ch1 = (raw_adc * (vdiv_ch1 / ADC_CODE_PER_DIV)) - ofst_ch1
    
    num_points = len(volts_ch1)
    times = np.linspace(0, actual_time, num_points)
    actual_sample_rate = num_points / actual_time
    
    # --- 8. DOWNSAMPLING AVANZATO (MEDIA E DEV. STD) ---
    print("Downsampling intelligente (Media e DevStd a blocchi)...")
    
    BLOCK_SIZE = max(1, num_points // TARGET_CSV_POINTS) 
    valid_length = (num_points // BLOCK_SIZE) * BLOCK_SIZE
    
    volts_blocks = volts_ch1[:valid_length].reshape(-1, BLOCK_SIZE)
    times_blocks = times[:valid_length].reshape(-1, BLOCK_SIZE)
    
    volts_mean = np.mean(volts_blocks, axis=1)
    volts_std  = np.std(volts_blocks, axis=1)
    times_mean = np.mean(times_blocks, axis=1)
    
    final_dt = times_mean[1] - times_mean[0] if len(times_mean) > 1 else 0
    final_points = len(volts_mean)

    print(f"Compressione: ridotto da {num_points} a {final_points} punti (Blocchi da {BLOCK_SIZE}).")
    print(f"Risoluzione temporale CSV: 1 punto ogni {final_dt*1000:.3f} ms.")

    # --- 8b. AGGIORNAMENTO FILE DI SETUP ---
    with open(file_setup, 'a', encoding='utf-8') as fs:
        fs.write("\n--- RISULTATI ACQUISIZIONE HARDWARE ---\n")
        fs.write(f"Punti grezzi scaricati: {num_points} ({data_len/1000000:.2f} MB)\n")
        fs.write(f"Sample Rate Oscilloscopio: {actual_sample_rate / 1000000:.2f} MSa/s\n")
        fs.write(f"Fattore di Downsampling (Block Size): {BLOCK_SIZE} punti per blocco\n")
        fs.write(f"Punti finali salvati in CSV: {final_points}\n")
        fs.write(f"Risoluzione temporale CSV (dt): {final_dt:.6f} secondi\n")

    # --- 9. SALVATAGGIO CSV E PLOT FINALE ---
    print("Salvataggio CSV...")
    with open(file_dati, mode='w', newline='') as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(['Time_s', 'Mean_CH1_V', 'StdDev_CH1_V'])
        
        for t, m, s in zip(times_mean, volts_mean, volts_std):
            writer.writerow([round(t, 6), round(m, 4), round(s, 4)])

    print("Generazione grafico con banda di deviazione standard...")
    plt.figure(figsize=(12, 6))
    
    plt.plot(times_mean, volts_mean, 'b-', linewidth=1.5, label='Media Segnale')
    plt.fill_between(times_mean, 
                     volts_mean - volts_std, 
                     volts_mean + volts_std, 
                     color='blue', alpha=0.3, label='Deviazione Standard (Rumore)')
    
    plt.xlabel('Tempo (s)')
    plt.ylabel('Tensione CH1 (V)')
    plt.title(f'Acquisizione Transiente (High-Speed Bulk) - {nome_base}')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    
    plt.savefig(file_grafico, dpi=300, bbox_inches='tight')
    print(f"✅ Esperimento concluso! Tutti i file sono in: {cartella_acquisizione}")
    
    plt.show()

if __name__ == '__main__':
    main()