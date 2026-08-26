import time
from arduino_thermal import ThermalController

# --- Configurazione Test ---
PORTA_SERIALE = '/dev/ttyACM0' 
TARGET_TEMP = 75.0  

print(f"Inizializzazione del test PID. Temperatura bersaglio: {TARGET_TEMP} °C")
controller = ThermalController(port=PORTA_SERIALE, target_temp=TARGET_TEMP)

print("Sistema armato. Il PID sta lavorando. (Premi Ctrl+C per fermare)")
print("-" * 50)

try:
    while True:
        if controller.current_temp > 0:
            print(f"Target: {TARGET_TEMP} °C | Temp. Reale: {controller.current_temp:.1f} °C | Errore Accumulato (Ki): {controller.integral:.2f}")
            
        time.sleep(1)

except KeyboardInterrupt:
    print("\nInterruzione manuale (Ctrl+C).")
    print("Spegnimento di sicurezza del Kapton e del Laser in corso...")
    controller.spegni_tutto()
    print("Sistema spento. Fine del test.")
