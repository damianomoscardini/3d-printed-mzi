import time
from pyfirmata2 import Arduino

class ThermalController:
    def __init__(self, port):
        print(f"Inizializzazione Arduino su {port} (Modalità Open-Loop Potenza)...")
        self.board = Arduino(port)
        
        # Solo i due pin output
        self.laser = self.board.get_pin('d:9:o')   
        self.kapton = self.board.get_pin('d:10:p') 
        
        # Spegnimento di sicurezza all'avvio
        self.laser.write(0)
        self.kapton.write(0)
        
    def accendi_laser(self):
        self.laser.write(1)

    def imposta_kapton(self, pwm_val):
        """
        Imposta la potenza della striscia Kapton.
        pwm_val: float tra 0.0 (spento) e 1.0 (100% di potenza, 14W)
        """
        val = max(0.0, min(1.0, float(pwm_val)))
        self.kapton.write(val)
        
    def spegni_tutto(self):
        self.laser.write(0)
        self.kapton.write(0)
        self.board.exit()