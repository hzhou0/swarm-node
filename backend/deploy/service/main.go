package main

import (
	"fmt"
	"gopkg.in/natefinch/lumberjack.v2"
	"log"
	"net/http"
	"os"
	"path/filepath"
)

func systemRead(w http.ResponseWriter, r *http.Request) {

}

func systemUpdate(w http.ResponseWriter, r *http.Request) {

}

func system(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		systemRead(w, r)
	} else if r.Method == http.MethodPut {
		systemUpdate(w, r)
	}
}

func main() {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		log.Fatalln("Error getting home directory: ", err)
	}
	rootDir := filepath.Join(homeDir, "SwarmNode")
	err = os.MkdirAll(rootDir, 0755)
	if err != nil {
		log.Fatalln("Error creating root directory: ", err)
	}
	logDir := filepath.Join(rootDir, "logs")
	err = os.MkdirAll(logDir, 0755)
	if err != nil {
		log.Fatalln("Error creating log directory: ", err)
	}
	log.SetFlags(log.Ldate | log.Ltime | log.LUTC | log.Lshortfile)
	log.SetOutput(&lumberjack.Logger{
		Filename:   filepath.Join(logDir, "deployment_server.log"),
		MaxSize:    10,
		MaxBackups: 3,
	})

	cloudflareSetupOrPanic(filepath.Join(homeDir, "CLOUDFLARE_TOKEN.json"), filepath.Join(homeDir, "CLOUDFLARE_TUNNEL.json"))

	http.Handle("/log", http.FileServer(http.Dir(logDir)))
	http.HandleFunc("/api/system", system)
	err = http.ListenAndServe(":7778", nil)
	if err != nil {
		fmt.Println("Error:", err)
	}
}
