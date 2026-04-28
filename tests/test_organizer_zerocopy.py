import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import os
from smartmule.organizer import LibraryOrganizer

"""
TEST SUITE: VALIDACIÓN DE LÓGICA 'ZERO-COPY' Y AFINIDAD DE DISPOSITIVO

Este test verifica que SmartMule sea capaz de distinguir entre particiones físicas 
y elija el algoritmo de movimiento más eficiente para cada escenario:

1. Mismo Dispositivo (Intra-partición):
   - Objetivo: Garantizar complejidad O(1) (movimiento instantáneo de punteros).
   - Verificación: Se mockea os.stat().st_dev para que coincidan.
   - Resultado esperado: Llamada exclusiva a os.rename().

2. Distinto Dispositivo (Inter-partición):
   - Objetivo: Evitar bloqueos y alertar sobre operaciones pesadas => O(N).
   - Verificación: Se simulan IDs de dispositivos distintos en origen y destino.
   - Resultado esperado: Llamada a shutil.move() y registro de log de advertencia.

"""

class TestZeroCopyLogic(unittest.TestCase):

    def setUp(self):
        self.organizer = LibraryOrganizer()
        self.src = Path("test_incoming/file.mkv")
        self.dest = Path("test_library/file.mkv")

    @patch("os.stat")
    def test_is_same_device_true(self, mock_stat):
        """Prueba que detecta correctamente cuando es el MISMO disco"""
        # Simulamos que ambos devuelven el mismo ID de dispositivo (99)
        mock_stat.return_value.st_dev = 99
        
        # Ejecutamos la validación interna
        result = self.organizer._is_same_device(self.src, self.dest)
        
        self.assertTrue(result, "Debería detectar que es el mismo dispositivo")

    @patch("os.stat")
    def test_is_same_device_false(self, mock_stat):
        """Prueba que detecta correctamente cuando son DISCOS DISTINTOS"""
        # Simulamos st_dev diferentes para origen y destino
        def side_effect(path):
            mock = MagicMock()
            if "test_incoming" in str(path):
                mock.st_dev = 1  # Disco C:
            else:
                mock.st_dev = 2  # Disco D:
            return mock
            
        mock_stat.side_effect = side_effect
        
        result = self.organizer._is_same_device(self.src, self.dest)
        
        self.assertFalse(result, "Debería detectar que son dispositivos diferentes")

    @patch("os.rename")
    @patch("shutil.move")
    @patch("smartmule.organizer.LibraryOrganizer._is_same_device")
    def test_transfer_mode_move_optimization(self, mock_check, mock_move, mock_rename):
        """Verifica que usa os.rename si es el mismo disco y shutil.move si no lo es"""
        
        # ESCENARIO A: Mismo disco -> Debería usar os.rename (Instantáneo)
        mock_check.return_value = True
        with patch("smartmule.organizer.ORGANIZER_MODE", "move"):
            self.organizer._transfer_item(self.src, self.dest)
            mock_rename.assert_called_once()
            mock_move.assert_not_called()
            
        mock_rename.reset_mock()
        mock_move.reset_mock()

        # ESCENARIO B: Distinto disco -> Debería usar shutil.move (Copia + Borra)
        mock_check.return_value = False
        with patch("smartmule.organizer.ORGANIZER_MODE", "move"):
            self.organizer._transfer_item(self.src, self.dest)
            mock_move.assert_called_once()
            mock_rename.assert_not_called()

if __name__ == "__main__":
    unittest.main()
