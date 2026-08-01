import os
import sys
import csv
import time
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pyvisa

# Forza il backend per la visualizzazione corretta su Linux/X11
os.environ['MPLBACKEND'] = 'TkAgg'
import matplotlib.pyplot as plt

# ==========================================
# CONFIGURAZIONE DITTATORIALE
# ==========================================
# Nessun default nascosto. Il codice esegue ESATTAMENTE questo.
acquisition_config = {
    'OSCILLOSCOPE_IP': '169.254.235.175',
    'INTERVAL_S': 0.5,       # Ogni quanti secondi chiedere il dato all'oscilloscopio
    'V_DIV_CH1': 5,          # Scala verticale CH1
    'V_DIV_CH2': 5,          # Scala verticale CH2
    'T_DIV': 5,              # La base tempi DELLO SCHERMO (influenza su quanti secondi fa la media)
    'PROBE_ATT': 10          # Attenuazione sonda
}

def main():
    # Estrazione rigorosa dei parametri
    osc_ip = acquisition_config['OSCILLOSCOPE_IP']
    interval_s = acquisition_config['INTERVAL_S']
    v_div_ch1 = acquisition_config['V_DIV_CH1']
    v_div_ch2 = acquisition_config['V_DIV_CH2']
    t_div = acquisition_config['T_DIV']
    probe_att = acquisition_config['PROBE_ATT']

    # ==========================================
    # 1. GESTIONE DIRECTORY E TIMEZONE
    # ==========================================
    tz_rome = ZoneInfo("Europe/Rome")
    start_time_dt = datetime.now(tz_rome)

    date_str = start_time_dt.strftime('%Y%m%d')  
    time_str = start_time_dt.strftime('%H%M')     
    base_name = f"{date_str}_{time_str}_continuous"

    # Struttura cartelle: continuous/acquisitions_continuous/YYYYMMDD/YYYYMMDD_HHMM_continuous
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    acq_folder = os.path.join(SCRIPT_DIR, "acquisitions_continuous", date_str, base_name)
    os.makedirs(acq_folder, exist_ok=True)

    file_data = os.path.join(acq_folder, f"{base_name}_data.csv")
    file_json = os.path.join(acq_folder, f"{base_name}_meta.json")
    file_plot = os.path.join(acq_folder, f"{base_name}_plot.svg")

    # ==========================================
    # 2. CONNESSIONE E SETUP OSCILLOSCOPIO
    # ==========================================
    rm = pyvisa.ResourceManager('@py')
    resource_string = f"TCPIP0::{osc_ip}::inst0::INSTR"

    print(f"Connecting to {resource_string}...")
    try:
        inst = rm.open_resource(resource_string)
        inst.timeout = 2000
    except Exception as e:
        print(f"PyVISA connection error: {e}")
        return

    idn = inst.query("*IDN?").strip()
    print(f"Connected to: {idn}")
    
    print("Configuring oscilloscope parameters for continuous polling...")
    # Disabilita l'invio degli header lunghi per facilitare il parsing dei numeri
    inst.write("CHDR OFF") 
    
    inst.write(f"CHAN1:PROB {probe_att}")
    inst.write(f"CHAN2:PROB {probe_att}")
    inst.write(f"CHAN1:SCAL {v_div_ch1}")
    inst.write(f"CHAN2:SCAL {v_div_ch2}")
    inst.write(f"TIM:SCAL {t_div}")
    
    print(f"Time/Div set to {t_div} s/div. The scope will average over a {t_div * 10}s rolling window.")

    # ==========================================
    # 3. PREPARAZIONE FILE DATI E PLOT LIVE
    # ==========================================
    f_csv = open(file_data, mode='w', newline='')
    writer = csv.writer(f_csv)
    header = ['Timestamp', 'Time_s', 'Mean_CH1_V', 'StdDev_CH1_V', 'Mean_CH2_V', 'StdDev_CH2_V']
    writer.writerow(header)

    plt.ion()  
    fig_rt, (ax1_rt, ax2_rt) = plt.subplots(2, 1, sharex=True, figsize=(10, 8))

    line1, = ax1_rt.plot([], [], 'orange', label="CH1 Mean (V)", linewidth=2)
    line2, = ax2_rt.plot([], [], 'blue', label="CH2 Mean (V)", linewidth=2)

    ax1_rt.set_ylabel('CH1 Voltage (V)')
    ax2_rt.set_ylabel('CH2 Voltage (V)')
    ax2_rt.set_xlabel('Time (s)')
    ax1_rt.set_title(f'Environmental Drift Monitoring - {base_name}')
    ax1_rt.legend(loc='upper right')
    ax2_rt.legend(loc='upper right')
    ax1_rt.grid(True)
    ax2_rt.grid(True)

    times, v1_list, v2_list = [], [], []
    start_time = time.time()

    print(f"\n[!] Acquisition started. Data saving to: {acq_folder}")
    print("[!] PRESS CTRL+C IN THIS TERMINAL TO STOP RECORDING AND SAVE.\n")
    print(f"{'TIME':<12} | {'ELAPSED':<10} | {'CH1 MEAN (V)':<15} | {'CH2 MEAN (V)':<15}")
    print("-" * 60)

    # ==========================================
    # 4. LOOP INFINITO DI ACQUISIZIONE
    # ==========================================
    try:
        while True:
            loop_start = time.time()
            elapsed = loop_start - start_time

            # Query the oscilloscope for statistical data
            raw_ch1_mean = inst.query("C1:PAVA? MEAN").strip()
            raw_ch1_std  = inst.query("C1:PAVA? STDEV").strip()
            raw_ch2_mean = inst.query("C2:PAVA? MEAN").strip()
            raw_ch2_std  = inst.query("C2:PAVA? STDEV").strip()

            try:
                # Parsing pulito per rimuovere unità di misura (es. "4.50V" -> 4.50)
                v1_mean = float(raw_ch1_mean.split(',')[1].replace('V', '')) if ',' in raw_ch1_mean else float(raw_ch1_mean.replace('V', ''))
                v1_std  = float(raw_ch1_std.split(',')[1].replace('V', '')) if ',' in raw_ch1_std else float(raw_ch1_std.replace('V', ''))
                v2_mean = float(raw_ch2_mean.split(',')[1].replace('V', '')) if ',' in raw_ch2_mean else float(raw_ch2_mean.replace('V', ''))
                v2_std  = float(raw_ch2_std.split(',')[1].replace('V', '')) if ',' in raw_ch2_std else float(raw_ch2_std.replace('V', ''))

                ts_now = datetime.now(tz_rome).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                short_ts = ts_now.split(' ')[1][:-4] # Solo HH:MM:SS per il terminale

                # Scrittura su disco immediata per sicurezza anti-crash
                writer.writerow([ts_now, round(elapsed, 3), v1_mean, v1_std, v2_mean, v2_std])
                f_csv.flush()

                # Aggiornamento liste per il plot in RAM
                times.append(elapsed)
                v1_list.append(v1_mean)
                v2_list.append(v2_mean)

                # Mantieni la memoria leggera plottando al massimo gli ultimi 10000 punti
                if len(times) > 10000:
                    times.pop(0)
                    v1_list.pop(0)
                    v2_list.pop(0)

                # Aggiornamento grafico in tempo reale
                line1.set_xdata(times)
                line1.set_ydata(v1_list)
                line2.set_xdata(times)
                line2.set_ydata(v2_list)

                ax1_rt.relim()
                ax1_rt.autoscale_view()
                ax2_rt.relim()
                ax2_rt.autoscale_view()
                plt.pause(0.01)  # Mantiene vivo X11/TkAgg

                # Output terminale fisso (sovrascrive la riga con \r)
                sys.stdout.write(f"\r{short_ts:<12} | {elapsed:>7.1f} s  | {v1_mean:>10.4f} V    | {v2_mean:>10.4f} V   ")
                sys.stdout.flush()

            except Exception as parse_err:
                # In caso di errore temporaneo di rete o lettura, salta il giro senza crashare
                print(f"\n[Warning] Parsing error at {elapsed:.1f}s: {parse_err}. Skipping point.")

            # Attendi il tempo esatto rimasto per rispettare l'intervallo
            time_to_wait = interval_s - (time.time() - loop_start)
            if time_to_wait > 0:
                time.sleep(time_to_wait)

    except KeyboardInterrupt:
        # Quando l'utente preme CTRL+C
        print("\n\n[!] Stop signal received (CTRL+C). Finalizing data...")

    finally:
        # ==========================================
        # 5. CHIUSURA E SALVATAGGIO DEFINITIVO
        # ==========================================
        stop_time_dt = datetime.now(tz_rome)
        
        f_csv.close()
        try:
            inst.close()
        except:
            pass

        # Salvataggio del grafico SVG finale a risoluzione piena
        plt.ioff()
        plt.savefig(file_plot, format='svg', bbox_inches='tight')
        plt.close(fig_rt)

        # Creazione del JSON omnicomprensivo
        meta_data = {
            "instrument": idn,
            "acquisition_mode": "continuous",
            "start_time": start_time_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "stop_time": stop_time_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "total_duration_s": round((stop_time_dt - start_time_dt).total_seconds(), 2),
            "acquisition_config": acquisition_config
        }
        
        with open(file_json, 'w') as f_json:
            json.dump(meta_data, f_json, indent=4)

        print(f"✅ Acquisition successfully saved and closed.")
        print(f"📁 Files saved in: {acq_folder}")
        print(f"   - Data: {os.path.basename(file_data)}")
        print(f"   - Meta: {os.path.basename(file_json)}")
        print(f"   - Plot: {os.path.basename(file_plot)}")

if __name__ == '__main__':
    main()