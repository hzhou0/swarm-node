#!/bin/bash

SERVICE_NAME="webrtc-proxy"
BINARY_PATH="./webrtc-proxy"  # Path to your compiled binary
SERVICE_FILE="./WebRTCProxyService.service"  # Path to the service file

# Define paths for installation
INSTALL_BIN_PATH="/usr/local/bin/$SERVICE_NAME"
INSTALL_SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

# Custom group name
GROUP_NAME="webrtc"

# Check if the group exists, or create it
if ! getent group $GROUP_NAME > /dev/null 2>&1; then
    echo "Creating group '$GROUP_NAME'..."
    sudo groupadd $GROUP_NAME
else
    echo "Group '$GROUP_NAME' already exists."
fi

# Add the current user to the custom group
USER=$(whoami)
echo "Adding user '$USER' to group '$GROUP_NAME'..."
sudo usermod -a -G $GROUP_NAME $USER

# Install binary
if [ -f "$BINARY_PATH" ]; then
    echo "Installing binary to $INSTALL_BIN_PATH..."
    sudo cp "$BINARY_PATH" "$INSTALL_BIN_PATH"
    sudo chmod 0755 "$INSTALL_BIN_PATH"
else
    echo "Error: Binary file '$BINARY_PATH' not found!"
    exit 1
fi

# Install systemd service file
if [ -f "$SERVICE_FILE" ]; then
    echo "Installing service file to $INSTALL_SERVICE_PATH..."
    sudo cp "$SERVICE_FILE" "$INSTALL_SERVICE_PATH"
    sudo chmod 0644 "$INSTALL_SERVICE_PATH"
else
    echo "Error: Service file '$SERVICE_FILE' not found!"
    exit 1
fi

# Reload systemd to register the new service
echo "Reloading systemd..."
sudo systemctl daemon-reload

# Enable and start the service
echo "Enabling and starting $SERVICE_NAME service..."
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

echo "Installation complete. Check the service status with:"
echo "  systemctl status $SERVICE_NAME"