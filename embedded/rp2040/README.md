# Install Toolchain
```shell
sudo apt install cmake python3 build-essential gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib
```
## Building
Standard CMake build with CMakeLists.txt. Highly recommend the rest be done with Clion.

## Flashing

Mount the rp2040 board as a mass storage device and
drop `cmake-build-*/src/main.uf2` onto it. 

Optionally, this can be auomated with `picotool`.