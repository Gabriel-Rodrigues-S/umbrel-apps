"""Detector de rajada de token ausente/inválido (janela deslizante)."""
import threading
from collections import deque


class Rajada:
    def __init__(self, limite: int = 20, janela_s: float = 600):
        self.limite = limite
        self.janela_s = janela_s
        self._falhas: deque[float] = deque()
        self._ultimo_disparo: float | None = None
        self._dia = 0
        self._trava = threading.Lock()

    def contar(self, agora: float) -> bool:
        """Registra uma falha. True só quando passa do limite e não houve disparo na janela."""
        with self._trava:
            self._dia += 1
            self._falhas.append(agora)
            while self._falhas and self._falhas[0] <= agora - self.janela_s:
                self._falhas.popleft()
            if len(self._falhas) <= self.limite:
                return False
            if self._ultimo_disparo is not None and agora - self._ultimo_disparo < self.janela_s:
                return False
            self._ultimo_disparo = agora
            return True

    def total_do_dia(self) -> int:
        with self._trava:
            return self._dia

    def zerar_dia(self) -> None:
        with self._trava:
            self._dia = 0
