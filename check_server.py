"""
Script to check if HotPin WebServer is running and get its IP address.
"""
import socket
import requests

def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        # Connect to a remote address (doesn't actually send data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # If we can't get IP by connecting to remote host, try to get it differently
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip.startswith('127.'):
                # Try to get non-loopback IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                return local_ip
            return local_ip
        except:
            return "127.0.0.1"

def check_server_running():
    """Check if the HotPin server is running on port 8000."""
    try:
        response = requests.get(f"http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'ok' in data and data['ok']:
                return True
    except:
        pass
    
    # Also check for the server running on the local IP
    local_ip = get_local_ip()
    if local_ip and local_ip != "127.0.0.1":
        try:
            response = requests.get(f"http://{local_ip}:8000/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'ok' in data and data['ok']:
                    return True
        except:
            pass
    
    return False

def get_server_ip():
    """Try to find the IP address where the server is running."""
    # First check localhost
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            return "localhost"
    except:
        pass
    
    # Check local IP
    local_ip = get_local_ip()
    if local_ip and local_ip != "127.0.0.1":
        try:
            response = requests.get(f"http://{local_ip}:8000/health", timeout=5)
            if response.status_code == 200:
                return local_ip
        except:
            pass
    
    # If we still can't find it, return None
    return None

def print_server_info():
    """Print server information to help with configuration."""
    print("Checking for HotPin WebServer...")
    
    if check_server_running():
        server_ip = get_server_ip()
        if server_ip:
            print(f"[OK] HotPin WebServer is running at: http://{server_ip}:8000")
            print(f"WebSocket URL should be: ws://{server_ip}:8000/ws")
            print(f"You should update your firmware config to connect to: ws://{server_ip}:8000/ws?session=hotpin-01&token=mysecrettoken123")
        else:
            print("[OK] HotPin WebServer appears to be running but couldn't determine IP")
    else:
        print("[ERROR] HotPin WebServer is not running or not accessible on port 8000")
        print("To start the server:")
        print("  cd hotpin-webserver")
        print("  python -m venv venv")
        print("  source venv/bin/activate  # On Windows: venv\\Scripts\\activate")
        print("  pip install -r requirements.txt")
        print("  python -c \"from hotpin import server; server.run_server()\"")
        
if __name__ == "__main__":
    print_server_info()