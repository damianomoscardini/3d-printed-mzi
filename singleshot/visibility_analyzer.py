import os
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter, find_peaks
from scipy.interpolate import CubicSpline
from IPython.display import display

def analyze_visibility(base_path, analysis_config):
    """
    Reads raw data for ALL channels, extracts envelopes, calculates V(t),
    saves CSVs, and generates a beautiful combined dual-panel plot.
    Requires STRICT definition of analysis_config.
    """
    if not base_path:
        raise ValueError("ERRORE CRITICO: Devi fornire il base_path!")

    if not analysis_config:
        raise ValueError("ERRORE CRITICO: Devi fornire il dizionario 'analysis_config'!")

    date_time_str = os.path.basename(os.path.normpath(base_path))

    # === LETTURA METADATI DA DISCO ===
    json_filename = os.path.join(base_path, f"{date_time_str}_meta.json")
    if not os.path.exists(json_filename):
        raise FileNotFoundError(f"ERRORE CRITICO: Impossibile trovare il file dei metadati {json_filename}!")
        
    print(f"Loading metadata from saved file: {json_filename}")
    with open(json_filename, 'r') as f_json:
        meta_data = json.load(f_json)

    # Estrae i preamboli, se manca la chiave crasherà correttamente
    preambles = meta_data["preambles"]

    # Lettura rigorosa dei parametri di analisi
    prominence = analysis_config['prominence']
    sg_win = analysis_config['savgol_window']
    sg_poly = analysis_config['savgol_poly']

    colors = {
        'C1': {'raw': 'orange', 'smooth': 'darkorange', 'env': 'red', 'name': 'Ch1'},
        'C2': {'raw': 'cornflowerblue', 'smooth': 'mediumblue', 'env': 'darkcyan', 'name': 'Ch2'}
    }

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
    print("\nStarting Visibility Analysis on all available channels...")

    for ch, preamble in preambles.items():
        bin_filename = os.path.join(base_path, f"{date_time_str}_data_{ch}.bin")
        if not os.path.exists(bin_filename):
            continue
            
        print(f"  > Processing {ch}...")
        
        with open(bin_filename, 'rb') as f:
            full_bin_data = f.read()
            
        dtype = np.int16 if preamble['adc_bit'] > 8 else np.int8
        arr_full = np.frombuffer(full_bin_data, dtype=dtype)
        
        step = max(1, len(arr_full) // 10000) 
        arr_ds = arr_full[::step]
        volts = (arr_ds / preamble['code_per_div']) * preamble['vdiv'] - preamble['offset']
        
        trigger_index = int(len(arr_ds) * 0.1)
        relative_indices = np.arange(len(arr_ds)) - trigger_index
        time_step = preamble['interval'] * step
        times = relative_indices * time_step

        if sg_win % 2 == 0: sg_win += 1 
        volts_smooth = savgol_filter(volts, window_length=sg_win, polyorder=sg_poly)

        peaks_idx, _ = find_peaks(volts_smooth, prominence=prominence)
        valls_idx, _ = find_peaks(-volts_smooth, prominence=prominence)

        if len(peaks_idx) < 3 or len(valls_idx) < 3:
            print(f"    [!] Troppi pochi picchi in {ch}. Salto l'analisi per questo canale.")
            continue

        t_peaks, y_peaks = times[peaks_idx], volts_smooth[peaks_idx]
        t_valls, y_valls = times[valls_idx], volts_smooth[valls_idx]

        spline_max = CubicSpline(t_peaks, y_peaks)
        spline_min = CubicSpline(t_valls, y_valls)

        t_start = max(t_peaks[0], t_valls[0])
        t_stop = min(t_peaks[-1], t_valls[-1])
        valid_mask = (times >= t_start) & (times <= t_stop)
        t_valid = times[valid_mask]

        env_max_valid = spline_max(t_valid)
        env_min_valid = spline_min(t_valid)

        visibility = (env_max_valid - env_min_valid) / (env_max_valid + env_min_valid)

        csv_filename = os.path.join(base_path, f"{date_time_str}_{ch}_visibility.csv")
        header = "Time(s),Env_Max(V),Env_Min(V),Visibility"
        data_to_save = np.column_stack((t_valid, env_max_valid, env_min_valid, visibility))
        np.savetxt(csv_filename, data_to_save, delimiter=",", header=header, comments='')

        c_raw = colors.get(ch, colors['C1'])['raw']
        c_smooth = colors.get(ch, colors['C1'])['smooth']
        c_env = colors.get(ch, colors['C1'])['env']
        c_name = colors.get(ch, colors['C1'])['name']
        
        ax1.plot(times, volts, color=c_raw, alpha=0.3, label=f'{c_name} Raw')
        ax1.plot(times, volts_smooth, color=c_smooth, label=f'{c_name} Smoothed')
        ax1.plot(t_valid, env_max_valid, color=c_env, linestyle='--', linewidth=2, label=f'{c_name} Env')
        ax1.plot(t_valid, env_min_valid, color=c_env, linestyle='--', linewidth=2)
        ax1.scatter(t_peaks, y_peaks, color=c_env, s=15, zorder=5)
        ax1.scatter(t_valls, y_valls, color=c_env, s=15, zorder=5)

        ax2.plot(t_valid, visibility, color=c_env, linewidth=2, label=f'V(t) - {c_name}')

    ax1.set_ylabel("Voltage (V)")
    ax1.set_title(f"Mach-Zehnder Visibility Analysis - {date_time_str}")
    ax1.legend(loc='upper right', fontsize='small', ncol=2)
    ax1.grid(True)

    ax2.set_xlabel("Time (s)")
    ax2.set_ylabel("Visibility (0 to 1)")
    ax2.set_ylim(0, 1.1)
    ax2.legend(loc='upper right')
    ax2.grid(True)

    plt.tight_layout()
    
    svg_filename = os.path.join(base_path, f"{date_time_str}_visibility_plot.svg")
    plt.savefig(svg_filename, format='svg', bbox_inches='tight')
    
    display(fig)
    plt.close(fig)
    print(f"\nAnalysis complete! Combined plot saved to: {svg_filename}")