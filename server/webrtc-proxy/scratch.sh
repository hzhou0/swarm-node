gst-launch-1.0 videotestsrc pattern=ball is-live=true ! 'video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1' ! shmsink socket-path=/tmp/testsocket wait-for-connection=true
gst-launch-1.0 shmsrc socket-path=/tmp/testsocket is-live=true ! queue ! "video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1" ! rawvideoparse use-sink-caps=true ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! video/x-h264,stream-format=byte-stream ! avdec_h264 ! fpsdisplaysink

gst-launch-1.0 videotestsrc pattern=ball is-live=true ! 'video/x-raw,width=640,height=360,format=I420,framerate=(fraction)30/1' ! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=20 ! shmsink socket-path=/tmp/testsocket
gst-launch-1.0 shmsrc socket-path= is-live=true ! queue ! h264parse ! avdec_h264 ! fpsdisplaysink
appsrc format=time is-live=true do-timestamp=true name=src ! application/x-rtp