if (TARGET tinyusb_device)
    add_executable(main main.c
            cobs.h
            io.h
            servo.h
            i2c.h
            gpi.h
            spi.h
    )
    add_compile_definitions(USBD_PRODUCT="RP2040 DECEMBER")
    # pull in common dependencies
    target_link_libraries(main PRIVATE pico_stdlib hardware_pwm hardware_i2c hardware_spi)
    target_compile_features(main PRIVATE c_std_23)

    # enable usb output, disable uart output
    pico_enable_stdio_usb(main 1)
    pico_enable_stdio_uart(main 0)

    # use the faster non-compliant float lib
    pico_set_float_implementation(main pico)

    # create map/bin/hex/uf2 file etc.
    pico_add_extra_outputs(main)

elseif (PICO_ON_DEVICE)
    message(WARNING "not building hello_usb because TinyUSB submodule is not initialized in the SDK")
endif ()
