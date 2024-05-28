if (TARGET tinyusb_device)
    add_executable(main main.c
            cobs.h
            io.h)
    add_compile_definitions(USBD_PRODUCT="RP2040 DECEMBER")
    # pull in common dependencies
    target_link_libraries(main PRIVATE pico_stdlib hardware_pio hardware_pwm hardware_clocks)

    # enable usb output, disable uart output
    pico_enable_stdio_usb(main 1)
    pico_enable_stdio_uart(main 0)

    # create map/bin/hex/uf2 file etc.
    pico_add_extra_outputs(main)

elseif (PICO_ON_DEVICE)
    message(WARNING "not building hello_usb because TinyUSB submodule is not initialized in the SDK")
endif ()
