import os
import json
import numpy as np
import matplotlib.pyplot as plt
from IPython.display import display

def plot_acquisition(base_path):
    """
    Reads raw .bin files from disk, computes time/voltage math, and plots them.
    It automatically extracts the timestamp and loads ALL settings from _meta.json.
    """
    if not base_path:
        raise ValueError("ERRORE CRITICO: Devi fornire il base_path!")

    date_time_str = os.path.basename(os.path.normpath(base_path))

    # === LETTURA METADATI DA DISCO ===
    json_filename = os.path.join(base_path, f"{date_time_str}_meta.json")
    if not os.path.exists(json_filename):
        raise FileNotFoundError(f"ERRORE CRITICO: Impossibile trovare il file dei metadati {json_filename}!")
        
    print(f"Loading metadata from saved file: {json_filename}")
    with open(json_filename, 'r') as f_json:
        meta_data = json.load(f_json)

    # Lettura diretta: se mancano queste chiavi nel JSON, è giusto che crashi
    preambles = meta_data["preambles"]
    acquisition_config = meta_data["acquisition_config"]
    trig_level = acquisition_config["TRIG_LEVEL"]

    print("\nProcessing raw binary data from disk and generating plot...")
    plot_data = {}
    
    # -----------------------------------------------------
    # DATA PROCESSING
    # -----------------------------------------------------
    for ch, preamble in preambles.items():
        bin_filename = os.path.join(base_path, f"{date_time_str}_data_{ch}.bin")
        
        if not os.path.exists(bin_filename):
            print(f"Warning: File {bin_filename} not found.")
            continue
            
        with open(bin_filename, 'rb') as f:
            full_bin_data = f.read()
            
        dtype = np.int16 if preamble['adc_bit'] > 8 else np.int8
        arr_full = np.frombuffer(full_bin_data, dtype=dtype)
        
        step = max(1, len(arr_full) // 5000) 
        arr_ds = arr_full[::step]
        
        volts = (arr_ds / preamble['code_per_div']) * preamble['vdiv'] - preamble['offset']
        
        trigger_index = int(len(arr_ds) * 0.1)
        relative_indices = np.arange(len(arr_ds)) - trigger_index
        time_step = preamble['interval'] * step
        times = relative_indices * time_step
        
        plot_data[ch] = (times, volts)

    # -----------------------------------------------------
    # PLOTTING
    # -----------------------------------------------------
    if not plot_data:
        print("No valid data to plot.")
        return

    fig = plt.figure(figsize=(10, 6))
    
    if "C1" in plot_data:
        plt.plot(plot_data["C1"][0], plot_data["C1"][1], label='Channel 1', color='orange')
    if "C2" in plot_data:
        plt.plot(plot_data["C2"][0], plot_data["C2"][1], label='Channel 2', color='blue', alpha=0.8)
        
    plt.axvline(x=0, color='red', linestyle='--', linewidth=1.5, label='Trigger (t=0)')
    plt.axhline(y=trig_level, color='green', linestyle='--', linewidth=1.5, label=f'Trigger Level ({trig_level}V)')
        
    plt.title(f"Mach-Zehnder Interferometer - {date_time_str}")
    plt.xlabel("Time (s)")
    plt.ylabel("Voltage (V)")
    plt.legend()
    plt.grid(True)
    
    plot_filename = os.path.join(base_path, f"{date_time_str}_plot.svg")
    plt.savefig(plot_filename, format='svg', bbox_inches='tight')
    
    display(fig)
    plt.close(fig)
    
    print(f"Plot saved to: {plot_filename}")