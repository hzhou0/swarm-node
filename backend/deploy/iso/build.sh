#!/bin/bash
if [[ -z "$CF_TUNNEL_TOKEN" ]]; then
  echo "Error: CF_TUNNEL_TOKEN is not set."
  exit 1
fi
cd "$(dirname "$0")" || exit
mkdir -p dist
cd ./dist || exit
# Check if the required tools are installed
command -v xorriso >/dev/null 2>&1 || { echo >&2 "xorriso is required but not installed. Aborting."; exit 1; }

# Set the paths
original_iso="debian-12.4.0-amd64-netinst.iso"
output_iso="debian-12.4.0-amd64-autoinst.iso"
preseed_file="../preseed.cfg"
tmp_dir="./tmp"
# Delete the tmp directory if present
if [ -d "${tmp_dir}" ]; then
    sudo rm -rf "$tmp_dir"
fi

# URL of the Debian ISO
iso_url="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/${original_iso}"

# Download the Debian ISO if not present
if [ ! -f "${original_iso}" ]; then
    echo "Downloading Debian ISO..."
    wget "${iso_url}" -O "${original_iso}" || { echo >&2 "Failed to download Debian ISO. Aborting."; exit 1; }
fi

# Extract the contents of the original ISO
xorriso -osirrox on -indev "${original_iso}" -extract / "${tmp_dir}"

# Copy the preseed file to the appropriate location
sudo gunzip "${tmp_dir}"/install.amd/initrd.gz
sudo cp "${preseed_file}" ${tmp_dir}/"preseed.cfg"
sudo cp "../post_install.sh" ${tmp_dir}/"post_install.sh"
echo -e "\necho '$CF_TUNNEL_TOKEN' > /home/node/CF_TUNNEL_TOKEN" | sudo tee -a ${tmp_dir}/"post_install.sh" > /dev/null
sudo cp "../grub/grub.cfg" ${tmp_dir}/boot/grub/grub.cfg
sudo cp "../isolinux/gtk.cfg" ${tmp_dir}/isolinux/gtk.cfg
sudo cp "../isolinux/isolinux.cfg" ${tmp_dir}/isolinux/isolinux.cfg
sudo gzip "${tmp_dir}"/install.amd/initrd

cd "${tmp_dir}" || exit
chmod +w md5sum.txt
find . -follow -type f ! -name md5sum.txt -print0 | xargs -0 md5sum > md5sum.txt
chmod -w md5sum.txt
cd ..


sudo xorrisofs -o "${output_iso}" \
  -b isolinux/isolinux.bin -c isolinux/boot.cat \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
  -partition_offset 16 \
  -eltorito-alt-boot -e 'boot/grub/efi.img' -no-emul-boot \
  -isohybrid-gpt-basdat ${tmp_dir}

exit
xorriso -as mkisofs -o "${output_iso}" -r\
        -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
        -c isolinux/boot.cat -b isolinux/isolinux.bin -no-emul-boot \
        -boot-load-size 4 -boot-info-table ${tmp_dir}