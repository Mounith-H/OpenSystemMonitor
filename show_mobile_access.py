"""
Show local IP addresses for accessing the dashboard from mobile devices.
"""

import socket
import psutil

print("=" * 70)
print("📱 Mobile Access Information")
print("=" * 70)

def get_local_ip_addresses():
    """Get all local network IP addresses."""
    addresses = []
    
    # Get all network interfaces
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            # Only show IPv4 addresses that are not localhost
            if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                addresses.append({
                    'interface': interface,
                    'ip': addr.address
                })
    
    return addresses

# Get hostname
hostname = socket.gethostname()
print(f"\nComputer Name: {hostname}")

# Get IP addresses
addresses = get_local_ip_addresses()

if not addresses:
    print("\n❌ No network interfaces found!")
    print("   Make sure you're connected to WiFi or Ethernet.")
else:
    print(f"\n📡 Available Network Interfaces:")
    print("-" * 70)
    
    # Separate WiFi addresses from others
    wifi_addresses = []
    other_addresses = []
    
    for addr in addresses:
        # Filter out link-local addresses (169.254.x.x)
        if addr['ip'].startswith('169.254.'):
            continue
        
        if 'Wi-Fi' in addr['interface'] or 'Wireless' in addr['interface']:
            wifi_addresses.append(addr)
        else:
            other_addresses.append(addr)
    
    # Show WiFi addresses first (most likely needed for mobile)
    if wifi_addresses:
        print("\n   ✅ WiFi Connection (RECOMMENDED for mobile):")
        for addr in wifi_addresses:
            print(f"      Interface: {addr['interface']}")
            print(f"      📱 Mobile URL: http://{addr['ip']}:8000")
    
    # Show other addresses
    if other_addresses:
        print("\n   🔌 Other Network Connections:")
        for addr in other_addresses:
            print(f"      Interface: {addr['interface']}")
            print(f"      URL: http://{addr['ip']}:8000")
    
    if not wifi_addresses and not other_addresses:
        print("\n   ⚠️  Only link-local addresses found (169.254.x.x)")
        print("      These won't work for mobile access.")
        print("      Please connect to a WiFi network.")


# Try to detect if firewall might be blocking
print("=" * 70)
print("🔍 Network Status:")
print("=" * 70)

# Check if server is running
server_running = False
try:
    import requests
    try:
        response = requests.get("http://localhost:8000/health", timeout=2)
        if response.status_code == 200:
            print("✅ Server is running on localhost")
            server_running = True
            if addresses:
                print(f"✅ You should be able to access from mobile at:")
                wifi_addrs = [a for a in addresses if not a['ip'].startswith('169.254.')]
                for addr in wifi_addrs[:3]:  # Show max 3 addresses
                    print(f"   http://{addr['ip']}:8000")
        else:
            print("⚠️  Server responded but with unexpected status")
    except requests.exceptions.Timeout:
        print("❌ Server is NOT running (connection timeout)")
        print("   Please start the server first using: monitor.bat")
    except requests.exceptions.ConnectionError:
        print("❌ Server is NOT running!")
        print("   Please start the server first using: monitor.bat")
    except Exception as e:
        print(f"⚠️  Could not check server status: {type(e).__name__}")
except ImportError:
    print("ℹ️  Cannot verify server status (requests module not installed)")
    print("   Install it with: pip install requests")
    print("   Server may still be running - try the URLs above!")
except KeyboardInterrupt:
    print("\n\n⚠️  Cancelled by user")
    import sys
    sys.exit(0)

if not server_running:
    print("\n" + "=" * 70)
    print("📋 Next Steps:")
    print("=" * 70)
    print("1. Start the server: Run 'monitor.bat' as Administrator")
    print("2. Configure firewall: Run 'setup_firewall.bat' as Administrator")
    print("3. Connect from mobile: Open the WiFi URL shown above")

print("\n" + "=" * 70)
