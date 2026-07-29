import os
# FORCE the graphic backend at the OS level BEFORE anything else!
os.environ['MPLBACKEND'] = 'TkAgg'

import csv
from datetime import datetime
import time
from zoneinfo import ZoneInfo
import pyvisa
import numpy as np
import matplotlib.pyplot as plt

# --- MAIN CONFIGURATION ---
OSC_IP = '169.254.235.175'
TOTAL_TIME_S = 50          # Desired total event time (s)
TARGET_CSV_POINTS = 200000  # Target number of rows in the final CSV

# SCPI CODE_PER_DIV specific for Siglent HD series (12-bit models)
# 480 codes per division upscaled to 16-bit word length = 7680
CODE_PER_DIV = 7680.0  

def get_closest_tdiv(target_total_time):
    """Calculates the closest Time/Div step (1-2-5) for SDS824X HD (10 horizontal divisions)"""
    target_tdiv = target_total_time / 10.0  
    
    multipliers = [1.0, 2.0, 5.0]
    decades = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0]
    
    valid_tdivs = [m * d for d in decades for m in multipliers]
    
    for tdiv in valid_tdivs:
        if tdiv >= target_tdiv:
            return tdiv
    return valid_tdivs[-1]

def main():
    # --- 1. TIMEZONE & DIRECTORY MANAGEMENT ---
    ACQ_MODE = "singleshot"
    
    tz_rome = ZoneInfo("Europe/Rome")
    current_time = datetime.now(tz_rome)

    date_str = current_time.strftime('%Y%m%d')
    time_str = current_time.strftime('%H%M')
    base_name = f"{date_str}_{time_str}_{ACQ_MODE}"

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
        inst.timeout = 20000 
    except Exception as e:
        print(f"PyVISA connection error: {e}")
        return

    idn = inst.query("*IDN?")
    print(f"Connected to: {idn.strip()}")
    
    # --- 3. MATH AUTO-SETUP & INSTANT RECORDING BYPASS ---
    best_tdiv = get_closest_tdiv(TOTAL_TIME_S)
    actual_time = best_tdiv * 10.0 
    print(f"Requested {TOTAL_TIME_S}s. Time/Div set to {best_tdiv} s/div (Actual physical time covered: {actual_time}s)")
    
    settings_applied = []
    def apply_cmd(cmd):
        inst.write(cmd)
        settings_applied.append(cmd)

    apply_cmd("CHDR OFF")
    apply_cmd(f"TDIV {best_tdiv}S") 
    apply_cmd("MSIZ 50M") 
    
    # CRITICAL TRICK: Shift the trigger delay to the extreme left.
    # Moving it 4.8 divisions left leaves almost NO pre-trigger buffer to fill.
    # The oscilloscope will become "Ready" almost instantly.
    trigger_delay = best_tdiv * 4.8
    apply_cmd(f"TRDL {trigger_delay}S")
    
    # --- 4. CREATE SETUP FILE (INITIAL PART) ---
    with open(file_setup, 'w', encoding='utf-8') as fs:
        fs.write("--- MACH-ZEHNDER EXPERIMENT SETUP (FAST SINGLESHOT - DUAL CHANNEL) ---\n")
        fs.write(f"Instrument: {idn.strip()}\n")
        fs.write(f"Session Start: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        fs.write(f"Acquisition Mode: ZERO PRE-TRIGGER BULK BINARY (16-bit word length) - CH1 & CH2\n")
        fs.write(f"Total Time Requested: {TOTAL_TIME_S} sec (Physically covered: {actual_time} sec)\n")
        fs.write(f"Target CSV points: {TARGET_CSV_POINTS}\n")
        fs.write("\n--- SCPI COMMANDS SENT ---\n")
        for imp in settings_applied:
            fs.write(f"- {imp}\n")

    # --- 5. IMMEDIATE ACQUISITION (TAPE RECORDER MODE) ---
    print("\n[⏳] Arming oscilloscope to SINGLE (Zero pre-trigger mode)...")
    inst.write("TRMD SINGLE")
    
    print("    Waiting for oscilloscope to lock in (Status: Ready)...")
    try:
        # Wait for the scope to be fully Ready (will be super fast now thanks to TRDL)
        while True:
            status = inst.query("SAST?").strip()
            if "Ready" in status:
                break
            time.sleep(0.1)
            
        print("[⚡] Oscilloscope is READY! Forcing trigger now...")
        inst.write("FRTR")
        
        # Give the scope hardware time to process the trigger
        time.sleep(1.0) 
        
        print("[▶️] Trigger sent! Recording live data...")
        
        start_wait = time.time()
        while True:
            status = inst.query("SAST?").strip()
            elapsed_wait = time.time() - start_wait
            
            progress = min(elapsed_wait / actual_time, 1.0)
            bar_length = 40
            filled_len = int(bar_length * progress)
            bar = '█' * filled_len + '-' * (bar_length - filled_len)
            
            print(f"\r    Recording progress: |{bar}| {progress*100:>5.1f}% (Scope Status: {status})", end='\r')
            
            # Failsafe stop
            if "Stop" in status or "FStop" in status or elapsed_wait > (actual_time + 5.0):
                bar = '█' * bar_length
                print(f"\r    Recording progress: |{bar}| 100.0% (Scope Status: {status})")
                print("\n[!] ACQUISITION COMPLETED! Oscilloscope has stopped.")
                break
                
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n\nAcquisition canceled by user. Restoring oscilloscope to AUTO...")
        inst.write("TRDL 0") # Reset delay to center
        inst.write("TRMD AUTO")
        inst.close()
        return

    # --- 6. RAW WAVEFORM BULK DOWNLOAD (BULLETPROOF METHOD) ---
    print("\nDownloading raw waveforms and reading precise scales (CH1 & CH2)...")
    
    # Using the guaranteed Siglent SCPI commands for vertical scales
    vdiv_ch1 = float(inst.query("C1:VDIV?").strip().replace('V', ''))
    ofst_ch1 = float(inst.query("C1:OFST?").strip().replace('V', ''))
    
    inst.write("C1:WF? DAT2")
    raw_bytes_ch1 = inst.read_raw()

    vdiv_ch2 = float(inst.query("C2:VDIV?").strip().replace('V', ''))
    ofst_ch2 = float(inst.query("C2:OFST?").strip().replace('V', ''))
    
    inst.write("C2:WF? DAT2")
    raw_bytes_ch2 = inst.read_raw()

    # Cleanup scope state
    inst.write("TRDL 0") 
    inst.write("TRMD AUTO")
    inst.close()

    # Extract CH1 binary payload
    header_idx1 = raw_bytes_ch1.find(b'#9')
    if header_idx1 != -1:
        data_len1 = int(raw_bytes_ch1[header_idx1+2 : header_idx1+11])
        wave_data_ch1 = raw_bytes_ch1[header_idx1+11 : header_idx1+11+data_len1]
    else:
        print("Error: Binary header '#9' not found for CH1. Oscilloscope sent empty data.")
        return

    # Extract CH2 binary payload
    header_idx2 = raw_bytes_ch2.find(b'#9')
    if header_idx2 != -1:
        data_len2 = int(raw_bytes_ch2[header_idx2+2 : header_idx2+11])
        wave_data_ch2 = raw_bytes_ch2[header_idx2+11 : header_idx2+11+data_len2]
    else:
        print("Error: Binary header '#9' not found for CH2. Oscilloscope sent empty data.")
        return

    print(f"Downloaded {data_len1/1000000:.2f} MB (CH1) and {data_len2/1000000:.2f} MB (CH2) of raw data.")

    # --- 7. EXACT 16-BIT SIGNED BINARY DECODING ---
    print(f"Decoding 16-bit SIGNED data...")
    
    # Read as Signed 16-bit Little-Endian ('<i2')
    raw_adc1 = np.frombuffer(wave_data_ch1, dtype='<i2').astype(np.float32)
    raw_adc2 = np.frombuffer(wave_data_ch2, dtype='<i2').astype(np.float32)
    
    # Calculate exact voltages
    volts_ch1 = (raw_adc1 / CODE_PER_DIV) * vdiv_ch1 - ofst_ch1
    volts_ch2 = (raw_adc2 / CODE_PER_DIV) * vdiv_ch2 - ofst_ch2
    
    num_points = len(volts_ch1)
    times = np.linspace(0, actual_time, num_points)
    actual_sample_rate = num_points / actual_time
    
    # --- 8. ADVANCED DOWNSAMPLING (MEAN & STD DEV) ---
    print("Intelligent downsampling (Block Mean and StdDev)...")
    
    BLOCK_SIZE = max(1, num_points // TARGET_CSV_POINTS) 
    valid_length = (num_points // BLOCK_SIZE) * BLOCK_SIZE
    
    times_blocks = times[:valid_length].reshape(-1, BLOCK_SIZE)
    times_mean = np.mean(times_blocks, axis=1)

    volts_blocks_ch1 = volts_ch1[:valid_length].reshape(-1, BLOCK_SIZE)
    volts_mean_ch1 = np.mean(volts_blocks_ch1, axis=1)
    volts_std_ch1  = np.std(volts_blocks_ch1, axis=1)

    volts_blocks_ch2 = volts_ch2[:valid_length].reshape(-1, BLOCK_SIZE)
    volts_mean_ch2 = np.mean(volts_blocks_ch2, axis=1)
    volts_std_ch2  = np.std(volts_blocks_ch2, axis=1)
    
    final_dt = times_mean[1] - times_mean[0] if len(times_mean) > 1 else 0
    final_points = len(volts_mean_ch1)

    print(f"Compression: reduced from {num_points} to {final_points} points (Blocks of {BLOCK_SIZE}).")

    # --- 8b. SETUP FILE UPDATE ---
    with open(file_setup, 'a', encoding='utf-8') as fs:
        fs.write("\n--- HARDWARE ACQUISITION RESULTS (DUAL CHANNEL) ---\n")
        fs.write(f"Raw points downloaded per channel: {num_points}\n")
        fs.write(f"Oscilloscope Sample Rate: {actual_sample_rate / 1000000:.2f} MSa/s\n")
        fs.write(f"Downsampling Factor (Block Size): {BLOCK_SIZE} points per block\n")
        fs.write(f"Final points saved in CSV: {final_points}\n")
        fs.write(f"CSV Time Resolution (dt): {final_dt:.6f} seconds\n")

    # --- 9. CSV SAVING & FINAL PLOT ---
    print("Saving CSV (CH1 + CH2)...")
    with open(file_data, mode='w', newline='') as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(['Time_s', 'Mean_CH1_V', 'StdDev_CH1_V', 'Mean_CH2_V', 'StdDev_CH2_V'])
        
        for t, m1, s1, m2, s2 in zip(times_mean, volts_mean_ch1, volts_std_ch1, volts_mean_ch2, volts_std_ch2):
            writer.writerow([round(t, 6), round(m1, 4), round(s1, 4), round(m2, 4), round(s2, 4)])

    print("Generating 2-panel plot with Standard Deviation bands...")
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(12, 8))
    
    ax1.plot(times_mean, volts_mean_ch1, 'b-', linewidth=1.5, label='CH1 Mean')
    ax1.fill_between(times_mean, volts_mean_ch1 - volts_std_ch1, volts_mean_ch1 + volts_std_ch1, 
                     color='blue', alpha=0.3, label='CH1 StdDev (Noise)')
    ax1.set_ylabel('CH1 Voltage (V)')
    ax1.set_title(f'Dual-Channel Transient Acquisition (High-Speed) - {base_name}')
    ax1.legend(loc='upper right')
    ax1.grid(True, linestyle='--', alpha=0.6)

    ax2.plot(times_mean, volts_mean_ch2, 'r-', linewidth=1.5, label='CH2 Mean')
    ax2.fill_between(times_mean, volts_mean_ch2 - volts_std_ch2, volts_mean_ch2 + volts_std_ch2, 
                     color='red', alpha=0.3, label='CH2 StdDev (Noise)')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('CH2 Voltage (V)')
    ax2.legend(loc='upper right')
    ax2.grid(True, linestyle='--', alpha=0.6)

    plt.tight_layout()
    plt.savefig(file_plot, dpi=300, bbox_inches='tight')
    print(f"✅ Experiment concluded! All files (CSV, Setup, Plot) are located in: {acq_folder}")
    
    plt.show()

if __name__ == '__main__':
    main()
