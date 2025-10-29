"""Discovery module for WebSocket URL detection and advertising."""
import asyncio
import json
import socket
import threading
import time
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - interface listing will be limited")

try:
    from zeroconf import Zeroconf, ServiceInfo
    ZEROCFG_AVAILABLE = True
except ImportError:
    ZEROCFG_AVAILABLE = False
    logger.warning("zeroconf not available - mDNS advertising disabled")

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    logger.warning("qrcode not available - QR code printing disabled")


def get_primary_ip() -> str:
    """
    Get the primary IP address of this machine using the UDP socket trick.
    
    Returns:
        str: The primary IP address, or '127.0.0.1' if unable to determine
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        logger.warning("Could not determine primary IP, defaulting to localhost")
        return "127.0.0.1"


def list_ipv4_addresses() -> List[str]:
    """
    List all non-loopback IPv4 addresses on this machine.
    
    Returns:
        List[str]: List of IPv4 addresses
    """
    addresses = []
    
    if PSUTIL_AVAILABLE:
        # Use psutil for better interface detection
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if not ip.startswith("127.") and ip != "0.0.0.0":
                        addresses.append(ip)
    else:
        # Fallback method using socket
        try:
            hostname = socket.gethostname()
            # Get all IPs associated with hostname
            result = socket.getaddrinfo(hostname, None)
            for res in result:
                ip = res[4][0]
                if not ip.startswith("127.") and ip != "::1" and ":" not in ip:
                    if ip not in addresses:
                        addresses.append(ip)
        except Exception as e:
            logger.warning(f"Could not list IPv4 addresses: {e}")
    
    return addresses


def make_ws_url(ip: str, port: int, path: str, token: Optional[str] = None, use_tls: bool = False) -> str:
    """
    Create a WebSocket URL with the given parameters.
    
    Args:
        ip: The IP address
        port: The port number
        path: The WebSocket path
        token: Optional authentication token
        use_tls: Whether to use secure WebSocket (wss)
    
    Returns:
        str: The WebSocket URL
    """
    scheme = "wss" if use_tls else "ws"
    url = f"{scheme}://{ip}:{port}{path}"
    if token:
        url = f"{url}?token={token}"
    return url


class DiscoveryService:
    """Main discovery service that handles all detection and advertisement methods."""
    
    def __init__(self, port: int, path: str, token: Optional[str] = None, use_tls: bool = False):
        self.port = port
        self.path = path
        self.token = token
        self.use_tls = use_tls
        self.zeroconf = None
        self.udp_broadcaster = None
        self.is_running = False
    
    def discover_urls(self) -> List[str]:
        """
        Discover all potential WebSocket URLs for this server.
        
        Returns:
            List[str]: List of WebSocket URLs
        """
        urls = []
        
        # Add primary IP URL
        primary_ip = get_primary_ip()
        primary_url = make_ws_url(primary_ip, self.port, self.path, self.token, self.use_tls)
        urls.append(primary_url)
        
        # Add other non-loopback interfaces
        other_addresses = [ip for ip in list_ipv4_addresses() if ip != primary_ip]
        for addr in other_addresses:
            url = make_ws_url(addr, self.port, self.path, self.token, self.use_tls)
            urls.append(url)
        
        return urls
    
    def advertise_mdns(self, name: str = "HotpinServer", enable: bool = False):
        """
        Start mDNS advertisement of the WebSocket service.
        
        Args:
            name: The service name
            enable: Whether to enable mDNS advertisement
        """
        if not enable or not ZEROCFG_AVAILABLE:
            if not ZEROCFG_AVAILABLE:
                logger.warning("Zeroconf not available, skipping mDNS advertisement")
            return
        
        try:
            primary_ip = get_primary_ip()
            self.zeroconf = Zeroconf()
            
            # Convert IP to bytes format for mDNS
            ip_bytes = socket.inet_aton(primary_ip)
            
            # Create service information
            service_info = ServiceInfo(
                "_hotpin._tcp.local.",
                f"{name}._hotpin._tcp.local.",
                addresses=[ip_bytes],
                port=self.port,
                properties={
                    'path': self.path,
                    'tls': 'true' if self.use_tls else 'false',
                    'token_required': 'true' if self.token else 'false'
                },
                server=f"{name}.local."
            )
            
            self.zeroconf.register_service(service_info)
            logger.info(f"mDNS advertised as {name}._hotpin._tcp.local on port {self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start mDNS advertisement: {e}")
    
    def start_udp_broadcast(self, enable: bool = False, broadcast_port: int = 50000, 
                          broadcast_interval: int = 5):
        """
        Start UDP broadcast of the WebSocket URL.
        
        Args:
            enable: Whether to enable UDP broadcast
            broadcast_port: The port to broadcast to
            broadcast_interval: Interval in seconds between broadcasts
        """
        if not enable:
            return
        
        # Create a primary URL for broadcasting
        primary_url = make_ws_url(get_primary_ip(), self.port, self.path, self.token, self.use_tls)
        
        class UDPBroadcaster:
            def __init__(self, url: str, port: int, interval: int):
                self.url = url
                self.port = port
                self.interval = interval
                self.running = False
                self.thread = None
            
            def broadcast_loop(self):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    
                    while self.running:
                        # Send the URL as UTF-8
                        sock.sendto(self.url.encode('utf-8'), ('255.255.255.255', self.port))
                        time.sleep(self.interval)
                    
                    sock.close()
                except Exception as e:
                    logger.error(f"UDP broadcast error: {e}")
            
            def start(self):
                self.running = True
                self.thread = threading.Thread(target=self.broadcast_loop, daemon=True)
                self.thread.start()
                logger.info(f"UDP broadcast started on 255.255.255.255:{self.port}")
            
            def stop(self):
                self.running = False
                if self.thread:
                    self.thread.join(timeout=1)
        
        self.udp_broadcaster = UDPBroadcaster(primary_url, broadcast_port, broadcast_interval)
        self.udp_broadcaster.start()
    
    def print_qr_code(self, url: str, enable: bool = False):
        """
        Print an ASCII QR code for the given URL.
        
        Args:
            url: The URL to encode in QR code
            enable: Whether to print QR code
        """
        if not enable or not QR_AVAILABLE:
            if not QR_AVAILABLE and enable:
                logger.warning("qrcode not available, skipping QR code printing")
            return
        
        try:
            qr = qrcode.QRCode(version=1, box_size=2, border=4)
            qr.add_data(url)
            qr.make(fit=True)
            
            print("\n" + "="*50)
            print("HotPin Device WebSocket URL (QR Code):")
            print(url)
            print("-" * 50)
            qr.print_ascii()
            print("="*50 + "\n")
        except Exception as e:
            logger.error(f"Failed to generate QR code: {e}")
    
    def start_advertising(self, mdns_name: str = "HotpinServer", 
                         mdns_enable: bool = False,
                         udp_enable: bool = False, 
                         udp_port: int = 50000, 
                         udp_interval: int = 5,
                         qr_enable: bool = False):
        """
        Start all enabled advertising methods.
        
        Args:
            mdns_name: Name for mDNS advertisement
            mdns_enable: Whether to enable mDNS
            udp_enable: Whether to enable UDP broadcasting
            udp_port: UDP broadcast port
            udp_interval: UDP broadcast interval in seconds
            qr_enable: Whether to print QR code
        """
        self.is_running = True
        
        # Get primary URL for QR code and logging
        urls = self.discover_urls()
        primary_url = urls[0] if urls else make_ws_url("localhost", self.port, self.path, self.token, self.use_tls)
        
        # Print primary URL
        logger.info(f"Hotpin WebSocket URL (primary): {primary_url}")
        
        # Print additional interface URLs
        for i, url in enumerate(self.discover_urls()):
            if i == 0:
                continue  # Skip primary as it's already printed
            ip = url.split("://")[1].split(":")[0]
            logger.info(f"Interface {ip} -> Hotpin WS URL: {url}")
        
        # Print QR code if enabled
        if qr_enable:
            self.print_qr_code(primary_url, qr_enable)
        
        # Start mDNS advertisement if enabled
        self.advertise_mdns(mdns_name, mdns_enable)
        
        # Start UDP broadcast if enabled
        self.start_udp_broadcast(udp_enable, udp_port, udp_interval)
    
    def stop_advertising(self):
        """
        Stop all advertising methods and clean up resources.
        """
        self.is_running = False
        
        # Stop zeroconf if running
        if self.zeroconf:
            try:
                self.zeroconf.close()
                logger.info("mDNS advertisement stopped")
            except Exception as e:
                logger.error(f"Error stopping mDNS: {e}")
        
        # Stop UDP broadcaster if running
        if self.udp_broadcaster:
            try:
                self.udp_broadcaster.stop()
                logger.info("UDP broadcast stopped")
            except Exception as e:
                logger.error(f"Error stopping UDP broadcast: {e}")