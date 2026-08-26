import os
import json
import numpy as np
import matplotlib.pyplot as plt
from IPython.display import display

def plot_acquisition(base_path):
    if not base_path: raise ValueError("ERRORE CRITICO: Devi fornire il base_path!")
    date_time_str = os.path.basename(os.path.normpath(base_path))

    json_filename = os.path.join(base_path, f"{date_time_str}_meta.json")
    if not os.path.exists(json_filename): raise FileNotFoundError("Metadati non trovati!")
        
    with open(json_filename, 'r') as f_json:
        meta_data = json.load(f_json)

    preambles = meta_data["preambles"]
    acquisition_config = meta_data["acquisition_config"]
    trig_level = acquisition_config["TRIG_LEVEL"]
    kapton_log = meta_data.get("kapton_log", None)

    plot_data = {}
    
    for ch, preamble in preambles.items():
        bin_filename = os.path.join(base_path, f"{date_time_str}_data_{ch}.bin")
        if not os.path.exists(bin_filename): continue
            
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

    if not plot_data: return

    fig, ax1 = plt.subplots(figsize=(10, 6))
    
    if "C1" in plot_data:
        ax1.plot(plot_data["C1"][0], plot_data["C1"][1], label='Channel 1', color='orange')
    if "C2" in plot_data:
        ax1.plot(plot_data["C2"][0], plot_data["C2"][1], label='Channel 2', color='blue', alpha=0.8)
        
    ax1.axvline(x=0, color='red', linestyle='--', linewidth=1.5, label='Trigger (t=0)')
    ax1.axhline(y=trig_level, color='green', linestyle='--', linewidth=1.5, label=f'Trigger ({trig_level}V)')
        
    ax1.set_title(f"Mach-Zehnder Interferometer - {date_time_str}")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Voltage (V)")
    ax1.legend(loc='upper left')
    ax1.grid(True)
    
    # --- PLOT RISCALDAMENTO (Gradino / rettangolo) ---
    if kapton_log:
        t_start = kapton_log["t_start_s"]
        t_stop = kapton_log["t_stop_s"]
        pwm_perc = kapton_log["pwm"] * 100.0
        
        ax2 = ax1.twinx()
        ax2.set_ylim(0, 110) # 100% corrisponderà a quasi il tetto del grafico
        ax2.set_ylabel("Heating Power (%)", color='red', fontsize=12, fontweight='bold')
        ax2.tick_params(axis='y', labelcolor='red')
        
        # Disegniamo la scatola di riscaldamento
        ax2.fill_between([t_start, t_stop], 0, pwm_perc, color='red', alpha=0.15, label=f'Heater ON ({pwm_perc:.0f}%)')
        # Disegniamo il contorno superiore per chiarezza
        ax2.plot([t_start, t_start], [0, pwm_perc], color='red', linewidth=2)
        ax2.plot([t_start, t_stop], [pwm_perc, pwm_perc], color='red', linewidth=2)
        ax2.plot([t_stop, t_stop], [pwm_perc, 0], color='red', linewidth=2)
        ax2.legend(loc='upper right')

    plot_filename = os.path.join(base_path, f"{date_time_str}_plot.svg")
    plt.savefig(plot_filename, format='svg', bbox_inches='tight')
    
    display(fig)
    plt.close(fig)