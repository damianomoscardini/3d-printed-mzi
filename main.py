import pyvisa
import time
import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt

# --- CONFIGURAZIONE PRINCIPALE ---
OSC_IP = '192.168.1.100'  # Sostituisci con l'IP reale
INTERVAL_S = 0.5          
TOTAL_TIME_S = 3600       

def setup_oscilloscope(inst):
    settings_applied = []
    
    def apply_cmd(desc, cmd):
        inst.write(cmd)
        settings_applied.append(f"{desc}: {cmd}")

    # Trigger AUTO per un campionamento continuo
    apply_cmd("Trigger Mode", "TRIGger:MODE AUTO")
    return settings_applied

def main():
    # --- 1. GESTIONE TIMEZONE E NOMI CARTELLE ---
    tz_roma = ZoneInfo("Europe/Rome")
    ora_corrente = datetime.now(tz_roma)
    
    data_str = ora_corrente.strftime('%Y%m%d') 
    ora_str = ora_corrente.strftime('%H%M')    
    nome_base = f"{data_str}_{ora_str}"        
    
    cartella_giorno = os.path.join("acquisitions", data_str)
    os.makedirs(cartella_giorno, exist_ok=True)
    
    file_dati = os.path.join(cartella_giorno, f"{nome_base}.csv")
    file_setup = os.path.join(cartella_giorno, f"{nome_base}_setup.txt")
    file_grafico = os.path.join(cartella_giorno, f"{nome_base}_plot.png") 

    # --- 2. CONNESSIONE PYVISA ---
    rm = pyvisa.ResourceManager('@py') 
    resource_string = f"TCPIP0::{OSC_IP}::inst0::INSTR"
    
    print(f"Connessione a {resource_string}...")
    try:
        inst = rm.open_resource(resource_string)
        inst.timeout = 2000 
    except Exception as e:
        print(f"Errore di connessione PyVISA: {e}")
        return

    idn = inst.query("*IDN?")
    print(f"Connesso a: {idn.strip()}")
    impostazioni = setup_oscilloscope(inst)
    
    # --- 3. CREAZIONE FILE DI SETUP ---
    with open(file_setup, 'w', encoding='utf-8') as fs:
        fs.write("--- SETUP ESPERIMENTO MACH-ZEHNDER ---\n")
        fs.write(f"Strumento: {idn.strip()}\n")
        fs.write(f"Inizio Acquisizione (Roma): {ora_corrente.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fs.write(f"Durata Totale Impostata: {TOTAL_TIME_S} secondi\n")
        fs.write(f"Intervallo di campionamento loop: {INTERVAL_S} secondi\n")
        fs.write("\n--- COMANDI SCPI INVIATI AL SETUP ---\n")
        for imp in impostazioni:
            fs.write(f"- {imp}\n")

    # --- 4. PREPARAZIONE FILE CSV DATI ---
    f_csv = open(file_dati, mode='w', newline='')
    writer = csv.writer(f_csv)
    header = ['Timestamp', 'Time_s', 'Mean_CH1_V', 'StdDev_CH1_V', 'Mean_CH2_V', 'StdDev_CH2_V']
    writer.writerow(header)
    
    # --- 5. SETUP PLOT IN TEMPO REALE ---
    plt.ion() # Attiva modalità interattiva GUI
    fig_rt, (ax1_rt, ax2_rt) = plt.subplots(2, 1, sharex=True, figsize=(10, 8))
    
    line1, = ax1_rt.plot([], [], 'b-', label="CH1 Mean (V)")
    line2, = ax2_rt.plot([], [], 'r-', label="CH2 Mean (V)")
    
    ax1_rt.set_ylabel('Tensione CH1 (V)')
    ax2_rt.set_ylabel('Tensione CH2 (V)')
    ax2_rt.set_xlabel('Tempo (s)')
    ax1_rt.set_title(f'Monitoraggio in Diretta - Acq: {nome_base}')
    ax1_rt.legend()
    ax2_rt.legend()
    
    times, v1_list, v2_list = [], [], []
    start_time = time.time()

    print(f"\n[!] Inizio acquisizione. Dati in: {file_dati}")

    try:
        while True:
            current_time = time.time()
            elapsed = current_time - start_time
            
            if elapsed > TOTAL_TIME_S:
                break
                
            # Lettura hardware
            raw_ch1_mean = inst.query("C1:PAVA? MEAN")
            raw_ch1_std  = inst.query("C1:PAVA? STDEV")
            raw_ch2_mean = inst.query("C2:PAVA? MEAN")
            raw_ch2_std  = inst.query("C2:PAVA? STDEV")
            
            try:
                v1_mean = float(raw_ch1_mean.split(',')[1].replace('V', '').strip())
                v1_std  = float(raw_ch1_std.split(',')[1].replace('V', '').strip())
                v2_mean = float(raw_ch2_mean.split(',')[1].replace('V', '').strip())
                v2_std  = float(raw_ch2_std.split(',')[1].replace('V', '').strip())
                
                ts_now = datetime.now(tz_roma).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                writer.writerow([ts_now, round(elapsed, 3), v1_mean, v1_std, v2_mean, v2_std])
                f_csv.flush() 

                times.append(elapsed)
                v1_list.append(v1_mean)
                v2_list.append(v2_mean)
                
                # Finestra mobile di 1000 punti per il display live
                if len(times) > 1000:
                    times.pop(0)
                    v1_list.pop(0)
                    v2_list.pop(0)
                    
                line1.set_xdata(times)
                line1.set_ydata(v1_list)
                line2.set_xdata(times)
                line2.set_ydata(v2_list)
                
                ax1_rt.relim()
                ax1_rt.autoscale_view()
                ax2_rt.relim()
                ax2_rt.autoscale_view()
                plt.pause(0.01) # Aggiorna la UI
                
                tempo_rimasto = TOTAL_TIME_S - elapsed
                print(f"[{ts_now}] CH1: {v1_mean:.3f}V | CH2: {v2_mean:.3f}V | Rimasti: {tempo_rimasto:.0f}s")
                
            except Exception as parse_err:
                print(f"Errore parsing: {parse_err}")

            time_to_wait = INTERVAL_S - (time.time() - current_time)
            if time_to_wait > 0:
                time.sleep(time_to_wait)

    except KeyboardInterrupt:
        print("\nAcquisizione interrotta dall'utente.")
        
    finally:
        print("\nChiusura connessioni e salvataggio in corso...")
        f_csv.close()
        inst.close()
        
        plt.ioff()
        plt.close(fig_rt) 
        
        # --- GENERAZIONE GRAFICO PANORAMICO DAL CSV (PNG) ---
        print("Lettura file CSV per generare l'immagine completa...")
        full_times, full_v1, full_v2 = [], [], []
        
        with open(file_dati, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                full_times.append(float(row['Time_s']))
                full_v1.append(float(row['Mean_CH1_V']))
                full_v2.append(float(row['Mean_CH2_V']))
                
        fig_final, (ax1_f, ax2_f) = plt.subplots(2, 1, sharex=True, figsize=(12, 8))
        
        ax1_f.plot(full_times, full_v1, 'b-', label="CH1 Mean (V)", linewidth=1.5)
        ax2_f.plot(full_times, full_v2, 'r-', label="CH2 Mean (V)", linewidth=1.5)
        
        ax1_f.set_ylabel('Tensione CH1 (V)')
        ax2_f.set_ylabel('Tensione CH2 (V)')
        ax2_f.set_xlabel('Tempo (s)')
        ax1_f.set_title(f'Deriva Fasi Mach-Zehnder - Acquisizione Completa: {nome_base}')
        ax1_f.legend()
        ax2_f.legend()
        
        ax1_f.grid(True, linestyle='--', alpha=0.6)
        ax2_f.grid(True, linestyle='--', alpha=0.6)
        
        plt.savefig(file_grafico, dpi=300, bbox_inches='tight')
        print(f"✅ Grafico finale salvato in: {file_grafico}")
        
        plt.show() 

if __name__ == "__main__":
    main()