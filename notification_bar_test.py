#!/usr/bin/env python3
"""
Teste ADB: abre e fecha a barra de notificação.

Fluxo:
  1. Descobre a resolução da tela do dispositivo (adb shell wm size).
  2. Faz um swipe de cima para baixo (puxa a tela) para exibir a barra de notificação.
  3. Faz um swipe de baixo para cima para recolher a barra novamente.

Uso pretendido: rodar dentro de um teste LAVA. O script imprime marcadores
compatíveis com o formato de resultados do LAVA (lava-test-case) quando possível
e usa o código de saída (0 = sucesso, !=0 = falha) para o LAVA decidir pass/fail.

Exemplos:
    python3 notification_bar_test.py
    python3 notification_bar_test.py --serial 0123456789ABCDEF
    python3 notification_bar_test.py --hold 1.5 --repeat 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time


class AdbError(RuntimeError):
    """Falha ao executar um comando adb."""


def run_adb(args: list[str], serial: str | None, timeout: float = 30.0) -> str:
    """Executa um comando adb e devolve o stdout (texto). Lança AdbError em falha."""
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AdbError("adb não encontrado no PATH. Instale o platform-tools.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"Timeout ao executar: {' '.join(cmd)}") from exc

    if result.returncode != 0:
        raise AdbError(
            f"Comando falhou ({result.returncode}): {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def wait_for_device(serial: str | None, timeout: float = 60.0) -> None:
    """Aguarda o dispositivo ficar disponível para o adb."""
    run_adb(["wait-for-device"], serial, timeout=timeout)


def get_screen_size(serial: str | None) -> tuple[int, int]:
    """Devolve (largura, altura) em pixels a partir de `adb shell wm size`.

    A saída típica é 'Physical size: 1080x1920'. Quando há override,
    aparece também 'Override size: WxH' — nesse caso usamos o override.
    """
    output = run_adb(["shell", "wm", "size"], serial)
    override = re.search(r"Override size:\s*(\d+)x(\d+)", output)
    physical = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
    match = override or physical
    if not match:
        raise AdbError(f"Não foi possível ler a resolução da tela. Saída: {output!r}")
    return int(match.group(1)), int(match.group(2))


def swipe(serial: str | None, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
    """Executa um swipe (input swipe) de (x1,y1) até (x2,y2) na duração dada."""
    run_adb(
        ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
        serial,
    )


def open_notification_bar(serial: str | None, width: int, height: int, duration_ms: int) -> None:
    """Puxa a tela de cima para baixo para exibir a barra de notificação.

    Começa no topo (y pequeno) e desce até perto do meio/base da tela.
    """
    x = width // 2
    y_start = max(1, int(height * 0.02))
    y_end = int(height * 0.80)
    swipe(serial, x, y_start, x, y_end, duration_ms)


def close_notification_bar(serial: str | None, width: int, height: int, duration_ms: int) -> None:
    """Empurra a barra de notificação de baixo para cima, recolhendo-a."""
    x = width // 2
    y_start = int(height * 0.80)
    y_end = max(1, int(height * 0.02))
    swipe(serial, x, y_start, x, y_end, duration_ms)


def lava_case(name: str, result: str) -> None:
    """Imprime o marcador de resultado do LAVA para um caso de teste."""
    print(f"<LAVA_SIGNAL_TESTCASE TEST_CASE_ID={name} RESULT={result}>")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste ADB: abre e fecha a barra de notificação do dispositivo."
    )
    parser.add_argument(
        "-s", "--serial",
        help="Serial do dispositivo adb (se houver mais de um conectado).",
    )
    parser.add_argument(
        "--duration", type=int, default=400,
        help="Duração de cada swipe em ms (padrão: 400).",
    )
    parser.add_argument(
        "--hold", type=float, default=1.0,
        help="Tempo (s) com a barra aberta antes de fechar (padrão: 1.0).",
    )
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="Quantas vezes repetir o ciclo abrir/fechar (padrão: 1).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        wait_for_device(args.serial)
        width, height = get_screen_size(args.serial)
        print(f"Dispositivo pronto. Resolução detectada: {width}x{height}")
        lava_case("adb-connection", "pass")
    except AdbError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        lava_case("adb-connection", "fail")
        return 1

    exit_code = 0
    for i in range(1, args.repeat + 1):
        label = f"ciclo {i}/{args.repeat}"
        try:
            print(f"[{label}] Abrindo a barra de notificação…")
            open_notification_bar(args.serial, width, height, args.duration)
            time.sleep(args.hold)

            print(f"[{label}] Fechando a barra de notificação…")
            close_notification_bar(args.serial, width, height, args.duration)
            time.sleep(0.5)

            lava_case(f"notification-bar-cycle-{i}", "pass")
        except AdbError as exc:
            print(f"[{label}] ERRO: {exc}", file=sys.stderr)
            lava_case(f"notification-bar-cycle-{i}", "fail")
            exit_code = 1

    if exit_code == 0:
        print("Teste concluído com sucesso.")
    else:
        print("Teste concluído com falhas.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
