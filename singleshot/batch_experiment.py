import time
from scope_singleshot import acquire
from plotter_singleshot import plot_acquisition
from visibility_analyzer import analyze_visibility

def main():
    # ==============================================================================
    # CONFIGURAZIONE DEL BATCH (ESPERIMENTI AUTOMATICI)
    # ==============================================================================

    # Lista delle potenze da testare (da 10% a 100%)
    PWM_LIST = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    # Parametri di Sicurezza e Attesa
    MAX_JOULES = 200
    COOLDOWN_MINUTI = 5  # Tempo di attesa tra i test

    # Configurazione base dell'oscilloscopio
    base_acquisition_config = {
        'OSCILLOSCOPE_IP': '169.254.235.175',
        'V_DIV_CH1': 5,      
        'V_DIV_CH2': 5,      
        'T_DIV': 5,          
        'PROBE_ATT': 10,
        'TRIG_LEVEL': 5,     
        'TRIG_CH': 'C1',
        'ARDUINO_PORT': '/dev/ttyACM0',
        'LASER_WAIT_SEC': 10.0,
        'MAX_JOULES': MAX_JOULES
    }

    # Configurazione analisi 
    analysis_config = {
        'prominence': 1.0,
        'savgol_window': 51,  
        'savgol_poly': 3
    }

    print("="*60)
    print(f" INIZIO BATCH AUTOMATICO: {len(PWM_LIST)} ESPERIMENTI")
    print(f" Limite di sicurezza   : {MAX_JOULES} Joule")
    print(f" Tempo di cooldown     : {COOLDOWN_MINUTI} minuti tra i test")
    print(f" Tempo Totale Stimato  : ~{len(PWM_LIST) * (COOLDOWN_MINUTI + 1)} minuti")
    print("="*60)

    for i, pwm in enumerate(PWM_LIST):
        print(f"\n\n" + "#"*60)
        print(f" ESPERIMENTO {i+1}/{len(PWM_LIST)} | POTENZA KAPTON = {pwm*100:.0f}%")
        print("#"*60)
        
        # 1. Copiamo il dizionario base e aggiorniamo il PWM
        current_config = base_acquisition_config.copy()
        current_config['KAPTON_PWM'] = pwm
        
        # 2. ACQUISIZIONE
        print(f"\n[Fase 1/3] Avvio acquisizione dati (Hardware in funzione)...")
        base_path = acquire(current_config)
        
        if base_path:
            # 3. PLOT E ANALISI (Avviene in background)
            print(f"\n[Fase 2/3] Generazione grafici e salvataggio su disco...")
            try:
                plot_acquisition(base_path)
                analyze_visibility(base_path, analysis_config)
                print(f"  -> Dati ed SVG salvati correttamente in: {base_path}")
            except Exception as e:
                print(f"  [!] Errore durante la generazione dei grafici: {e}")
        else:
            print(f"\n[!] Errore critico nell'acquisizione dell'esperimento {i+1}. Salto al prossimo.")
            
        # 4. RAFFREDDAMENTO / COOLDOWN 
        if i < len(PWM_LIST) - 1:
            wait_seconds = int(COOLDOWN_MINUTI * 60)
            print(f"\n[Fase 3/3] Inizio cooldown di {COOLDOWN_MINUTI} minuti per smaltire il calore...")
            
            for remaining in range(wait_seconds, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(f"  Attendere prego: {mins:02d}:{secs:02d} rimanenti... ", end="\r", flush=True)
                time.sleep(1)
                
            print("  Cooldown completato! Sistema pronto per il prossimo test.    ")

    print("\n\n" + "="*60)
    print(" BATCH COMPLETATO CON SUCCESSO! ")
    print(" Puoi sfogliare le cartelle 'acquisitions_singleshot' per i risultati.")
    print("="*60)

if __name__ == "__main__":
    main()