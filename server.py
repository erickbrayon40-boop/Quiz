"""Inicializacao do servidor local do quiz no Windows e em outros sistemas."""
import os
import socket
from waitress import serve


def main(application):
    port = int(os.environ.get('PORT', 5000))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            print(f'Ja existe um servidor na porta {port}. Feche o terminal anterior antes de iniciar novamente.', flush=True)
            return
    local_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as network:
            network.connect(('8.8.8.8', 80))
            local_ip = network.getsockname()[0]
    except OSError:
        pass
    print(f'Quiz disponivel em: http://127.0.0.1:{port}', flush=True)
    if local_ip:
        print(f'Na mesma rede: http://{local_ip}:{port}', flush=True)
    print('Mantenha esta janela aberta. Pressione Ctrl+C para encerrar.', flush=True)
    try:
        serve(application, host='0.0.0.0', port=port, threads=8)
    except OSError as exc:
        print(f'Nao foi possivel iniciar na porta {port}: {exc}', flush=True)


if __name__ == '__main__':
    from app import app
    main(app)
