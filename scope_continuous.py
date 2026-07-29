import os
os.environ['MPLBACKEND'] = 'TkAgg'

import csv
from datetime import datetime
import time
from zoneinfo import ZoneInfo
import pyvisa
import matplotlib.pyplot as plt

# --- MAIN CONFIGURATION ---
OSC_IP = '169.254.235.175'  
INTERVAL_S = 0.5            # Loop sampling interval (seconds)
TOTAL_TIME_S = 120          # Total duration of the experiment (seconds)

# Parameters for Envelope Detection (Visibility)
WINDOW_SIZE = 150           
STEP = 30                   

def get_closest_tdiv(target_total_time):
    """Calculates the closest Time/Div step (1-2-5) for a 10-division grid."""
    target_tdiv = target_total_time / 10.0  
    
    multipliers = [1.0, 2.0, 5.0]
    decades = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0]
    
    valid_tdivs = [m * d for d in decades for m in multipliers]
    
    for tdiv in valid_tdivs:
        if tdiv >= target_tdiv:
            return tdiv
    return valid_tdivs[-1]

def setup_oscilloscope(inst, interval_s):
    settings_applied = []
    
    # Disable command headers to make parsing raw values easier
    inst.write("CHDR OFF")
    
    def apply_cmd(desc, cmd):
        inst.write(cmd)
        settings_applied.append(f"{desc}: {cmd}")
        
    apply_cmd("Trigger Mode", "TRMD AUTO")
    
    # Dynamically set Time/Div based on INTERVAL_S to fill the screen
    best_tdiv = get_closest_tdiv(interval_s)
    apply_cmd("Time/Div", f"TDIV {best_tdiv}S")
    
    return settings_applied, best_tdiv

def main():
    # --- 1. TIMEZONE & DIRECTORY MANAGEMENT ---
    ACQ_MODE = "continuous"
    
    tz_rome = ZoneInfo("Europe/Rome")
    current_time = datetime.now(tz_rome)

    date_str = current_time.strftime('%Y%m%d')  
    time_str = current_time.strftime('%H%M')     
    base_name = f"{date_str}_{time_str}_{ACQ_MODE}"

    # Folder Tree: acquisitions / continuous / YYYYMMDD / YYYYMMDD_HHMM_continuous
    acq_folder = os.path.join("acquisitions", ACQ_MODE, date_str, base_name)
    os.makedirs(acq_folder, exist_ok=True)

    file_data = os.path.join(acq_folder, f"{base_name}.csv")
    file_setup = os.path.join(acq_folder, f"{base_name}_setup.txt")
    file_plot = os.path.join(acq_folder, f"{base_name}_plot.png")

    # --- 2. PYVISA CONNECTION ---
    rm = pyvisa.ResourceManager('@py')
    resource_string = f"TCPIP0::{OSC_IP}::inst0::INSTR"

    print(f"Connecting to {resource_string}...")
    try:
        inst = rm.open_resource(resource_string)
        inst.timeout = 2000
    except Exception as e:
        print(f"PyVISA connection error: {e}")
        return

    idn = inst.query("*IDN?")
    print(f"Connected to: {idn.strip()}")
    settings, applied_tdiv = setup_oscilloscope(inst, INTERVAL_S)
    
    print(f"Time/Div dynamically set to: {applied_tdiv} s/div to match a {INTERVAL_S}s polling interval.")

    # --- 3. CREATE INITIAL SETUP FILE ---
    with open(file_setup, 'w', encoding='utf-8') as fs:
        fs.write("--- MACH-ZEHNDER EXPERIMENT SETUP (CONTINUOUS POLLING) ---\n")
        fs.write(f"Instrument: {idn.strip()}\n")
        fs.write(f"Acquisition Start: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fs.write(f"Total Duration Set: {TOTAL_TIME_S} seconds\n")
        fs.write(f"Loop Sampling Interval: {INTERVAL_S} seconds\n")
        fs.write(f"Auto-Calculated Time/Div: {applied_tdiv} s/div\n")
        fs.write("\n--- SCPI COMMANDS SENT ---\n")
        for setting in settings:
            fs.write(f"- {setting}\n")

    # --- 4. PREPARE DATA CSV FILE ---
    f_csv = open(file_data, mode='w', newline='')
    writer = csv.writer(f_csv)
    header = ['Timestamp', 'Time_s', 'Mean_CH1_V', 'StdDev_CH1_V', 'Mean_CH2_V', 'StdDev_CH2_V']
    writer.writerow(header)

    # --- 5. REAL-TIME PLOT SETUP ---
    plt.ion()  
    fig_rt, (ax1_rt, ax2_rt) = plt.subplots(2, 1, sharex=True, figsize=(10, 8))

    line1, = ax1_rt.plot([], [], 'b-', label="CH1 Mean (V)")
    line2, = ax2_rt.plot([], [], 'r-', label="CH2 Mean (V)")

    ax1_rt.set_ylabel('CH1 Voltage (V)')
    ax2_rt.set_ylabel('CH2 Voltage (V)')
    ax2_rt.set_xlabel('Time (s)')
    ax1_rt.set_title(f'Slow Drift Monitoring - Acq: {base_name}')
    ax1_rt.legend()
    ax2_rt.legend()

    times, v1_list, v2_list = [], [], []
    start_time = time.time()

    print(f"\n[!] Acquisition started. Data saving to: {acq_folder}")

    try:
        while True:
            loop_start = time.time()
            elapsed = loop_start - start_time

            if elapsed > TOTAL_TIME_S:
                # Print a final 100% progress bar before breaking
                bar = '█' * 30
                print(f"\r[{datetime.now(tz_rome).strftime('%H:%M:%S')}] Progress: |{bar}| 100.0% - Completed!    ")
                break

            # Query the oscilloscope
            raw_ch1_mean = inst.query("C1:PAVA? MEAN").strip()
            raw_ch1_std  = inst.query("C1:PAVA? STDEV").strip()
            raw_ch2_mean = inst.query("C2:PAVA? MEAN").strip()
            raw_ch2_std  = inst.query("C2:PAVA? STDEV").strip()

            try:
                # Handle potential formatting anomalies from the scope
                v1_mean = float(raw_ch1_mean.split(',')[1].replace('V', '')) if ',' in raw_ch1_mean else float(raw_ch1_mean.replace('V', ''))
                v1_std  = float(raw_ch1_std.split(',')[1].replace('V', '')) if ',' in raw_ch1_std else float(raw_ch1_std.replace('V', ''))
                v2_mean = float(raw_ch2_mean.split(',')[1].replace('V', '')) if ',' in raw_ch2_mean else float(raw_ch2_mean.replace('V', ''))
                v2_std  = float(raw_ch2_std.split(',')[1].replace('V', '')) if ',' in raw_ch2_std else float(raw_ch2_std.replace('V', ''))

                ts_now = datetime.now(tz_rome).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                short_ts = ts_now.split(' ')[1][:-4] # Just HH:MM:SS for the progress bar

                writer.writerow([ts_now, round(elapsed, 3), v1_mean, v1_std, v2_mean, v2_std])
                f_csv.flush()

                times.append(elapsed)
                v1_list.append(v1_mean)
                v2_list.append(v2_mean)

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
                plt.pause(0.01)  

                # Calculate progress and generate the loading bar
                progress = min(elapsed / TOTAL_TIME_S, 1.0)
                bar_length = 30
                filled_len = int(bar_length * progress)
                bar = '█' * filled_len + '-' * (bar_length - filled_len)
                
                # \r overwrites the current line in the terminal
                print(f"\r[{short_ts}] CH1:{v1_mean:>7.3f}V | CH2:{v2_mean:>7.3f}V | Progress: |{bar}| {progress*100:>5.1f}%", end='\r')

            except Exception as parse_err:
                print(f"\nParsing error: {parse_err}. Raw data: {raw_ch1_mean}")

            time_to_wait = INTERVAL_S - (time.time() - loop_start)
            if time_to_wait > 0:
                time.sleep(time_to_wait)

    except KeyboardInterrupt:
        print("\n\nAcquisition interrupted by user.")

    finally:
        print("\nClosing connections and saving...")
        f_csv.close()
        inst.close()

        plt.ioff()
        plt.close(fig_rt)

        # --- FINAL PLOT & VISIBILITY CALCULATION (ENVELOPE DETECTION) ---
        print("Calculating Envelope Detection (Visibility over time)...")
        full_times, full_v1, full_v2 = [], [], []

        with open(file_data, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                full_times.append(float(row['Time_s']))
                full_v1.append(float(row['Mean_CH1_V']))
                full_v2.append(float(row['Mean_CH2_V']))

        vis_times, vis_ch1_list, vis_ch2_list = [], [], []

        if len(full_times) > WINDOW_SIZE:
            for i in range(0, len(full_times) - WINDOW_SIZE, STEP):
                v1_chunk = full_v1[i : i + WINDOW_SIZE]
                v2_chunk = full_v2[i : i + WINDOW_SIZE]
                t_chunk  = full_times[i : i + WINDOW_SIZE]

                v1_max, v1_min = max(v1_chunk), min(v1_chunk)
                v2_max, v2_min = max(v2_chunk), min(v2_chunk)

                vis1 = (v1_max - v1_min) / (v1_max + v1_min) if (v1_max + v1_min) != 0 else 0.0
                vis2 = (v2_max - v2_min) / (v2_max + v2_min) if (v2_max + v2_min) != 0 else 0.0

                vis_ch1_list.append(vis1)
                vis_ch2_list.append(vis2)
                vis_times.append(t_chunk[int(WINDOW_SIZE/2)])

            with open(file_setup, 'a', encoding='utf-8') as fs:
                fs.write("\n--- VISIBILITY ANALYSIS (ENVELOPE DETECTION) ---\n")
                fs.write(f"Initial Visibility CH1: {vis_ch1_list[0]:.4f}\n")
                fs.write(f"Final Visibility CH1: {vis_ch1_list[-1]:.4f}\n")
                fs.write(f"Initial Visibility CH2: {vis_ch2_list[0]:.4f}\n")
                fs.write(f"Final Visibility CH2: {vis_ch2_list[-1]:.4f}\n")

            print(f"\n📊 CH1 Visibility went from {vis_ch1_list[0]:.3f} to {vis_ch1_list[-1]:.3f}")

        # --- 3-PANEL FINAL PLOT ---
        fig_final, (ax1_f, ax2_f, ax3_f) = plt.subplots(3, 1, sharex=True, figsize=(12, 10))

        ax1_f.plot(full_times, full_v1, 'b-', label="CH1 Mean (V)", linewidth=1.5)
        ax2_f.plot(full_times, full_v2, 'r-', label="CH2 Mean (V)", linewidth=1.5)

        if vis_times:
            ax3_f.plot(vis_times, vis_ch1_list, 'k.-', label="CH1 Visibility", linewidth=1.5)
            ax3_f.plot(vis_times, vis_ch2_list, 'g.-', label="CH2 Visibility", linewidth=1.5)
            ax3_f.set_ylabel('Contrast (0 - 1)')
            ax3_f.set_ylim(0, 1)
            ax3_f.legend()
            ax3_f.grid(True, linestyle='--', alpha=0.6)

        ax1_f.set_ylabel('CH1 Voltage (V)')
        ax2_f.set_ylabel('CH2 Voltage (V)')
        ax3_f.set_xlabel('Time (s)')

        ax1_f.set_title(f'Mach-Zehnder Phase Drift - Acq: {base_name}')
        ax1_f.legend()
        ax2_f.legend()

        ax1_f.grid(True, linestyle='--', alpha=0.6)
        ax2_f.grid(True, linestyle='--', alpha=0.6)

        plt.tight_layout()
        plt.savefig(file_plot, dpi=300, bbox_inches='tight')
        print(f"✅ Final plot with visibility saved to: {file_plot}")

        plt.show()

if __name__ == '__main__':
    main()