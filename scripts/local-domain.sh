#!/usr/bin/env bash
# Serve the assistant at https://arnobotinteractiverobot.com on THIS Mac.
#
# Strictly local: the name resolves to 127.0.0.1 on this Mac only, and the app
# listens on 127.0.0.1 only, so nothing on the network or the internet can
# reach it.
#
# The microphone only works on localhost or over HTTPS, so a bare http:// name
# is not enough: this makes a private certificate authority, issues a
# certificate for the name, trusts that authority in the System keychain, and
# points the name at 127.0.0.1 in /etc/hosts. Ports 443/80 need root to bind,
# so a loopback-only firewall rule forwards them to the app's 8443/8080, and a
# launch daemon re-applies that rule at every boot.
#
# Run once from the project root:   bash scripts/local-domain.sh
# Undo:                             bash scripts/local-domain.sh --remove
set -euo pipefail

DOMAIN="${ROBOT_DOMAIN:-arnobotinteractiverobot.com}"
CERTS="$(cd "$(dirname "$0")/.." && pwd)/certs"
CA_NAME="Arnobot Interactive Robot Local CA"
HOSTS_LINE="127.0.0.1 $DOMAIN www.$DOMAIN"
ANCHOR="com.apple/arnobot-robot"          # /etc/pf.conf already evaluates com.apple/*
RULES="/etc/pf.anchors/arnobot-robot"
DAEMON="/Library/LaunchDaemons/com.arnobot.robot.pf.plist"

if [[ "${1:-}" == "--remove" ]]; then
  sudo sed -i '' "/ $DOMAIN www.$DOMAIN\$/d" /etc/hosts
  sudo security delete-certificate -c "$CA_NAME" /Library/Keychains/System.keychain || true
  sudo launchctl bootout system "$DAEMON" 2>/dev/null || true
  sudo rm -f "$DAEMON" "$RULES"
  sudo pfctl -a "$ANCHOR" -F all 2>/dev/null || true
  rm -rf "$CERTS"
  echo "Removed $DOMAIN from /etc/hosts, the port forward and its daemon,"
  echo "untrusted the local CA and deleted certs/."
  exit 0
fi

mkdir -p "$CERTS"
cd "$CERTS"

# 1. A private certificate authority, made once and kept.
if [[ ! -f ca.pem ]]; then
  openssl genrsa -out ca.key 2048 2>/dev/null
  openssl req -x509 -new -key ca.key -sha256 -days 825 -out ca.pem \
    -subj "/CN=$CA_NAME/O=Arnobot"
  chmod 600 ca.key
fi

# 2. The site certificate. 825 days is the most browsers accept.
cat > site.cnf <<CNF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = $DOMAIN
O = Arnobot
[ext]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:$DOMAIN, DNS:www.$DOMAIN, DNS:localhost, IP:127.0.0.1
CNF
openssl genrsa -out site.key 2048 2>/dev/null
openssl req -new -key site.key -out site.csr -config site.cnf
openssl x509 -req -in site.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out site.pem -days 825 -sha256 -extfile site.cnf -extensions ext 2>/dev/null
chmod 600 site.key
rm -f site.csr

# 3. Trust the CA, map the name, forward the ports (administrator password).
echo "Your Mac password is needed to trust the certificate, add the name"
echo "and forward ports 443/80 on 127.0.0.1 to the app:"
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain ca.pem
grep -qF "$HOSTS_LINE" /etc/hosts || echo "$HOSTS_LINE" | sudo tee -a /etc/hosts >/dev/null
sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder 2>/dev/null || true

# Loopback only: traffic to 127.0.0.1:443/80 goes to the app on 8443/8080.
# Nothing arriving from the network matches these rules.
sudo tee "$RULES" >/dev/null <<RULES_EOF
rdr pass on lo0 inet proto tcp from any to 127.0.0.1 port 443 -> 127.0.0.1 port 8443
rdr pass on lo0 inet proto tcp from any to 127.0.0.1 port 80 -> 127.0.0.1 port 8080
RULES_EOF
sudo tee "$DAEMON" >/dev/null <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.arnobot.robot.pf</string>
  <key>ProgramArguments</key>
  <array>
    <string>/sbin/pfctl</string><string>-E</string>
    <string>-a</string><string>$ANCHOR</string>
    <string>-f</string><string>$RULES</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
sudo launchctl bootout system "$DAEMON" 2>/dev/null || true
sudo launchctl bootstrap system "$DAEMON"

echo
echo "Done. Start the app with:  bash run.sh"
echo "Then open:                 https://$DOMAIN"
