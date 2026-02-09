# Ping-The-Route
A tool that combines traceroute and ping.
Made to ~~stare at it for 69 billion years straight~~ detect failing nodes.

**Dependencies:**
pyyaml, ping3

**Warning! The built executables can trigger AV heuristics and generic detections, because they're packed with PyInstaller. They're NOT malicious, this is a false positive.**

**Usage for ping_the_route_cli:**

```
positional arguments:
  target               IP or domain

options:
  -h, --help           show help message and exit
  --resolve-during     Resolve DNS during traceroute
  --resolve-after      Resolve hostnames after traceroute
  -c, --count COUNT    Ping count per hop
  --no-live            Disable live ping of target
  -o, --output OUTPUT  Save results to YAML file
```
**example input:**
`.\ping_the_route_cli.exe 1.1.1.1`

**example output:**
```
Live ping 1.1.1.1: 0.3 ms

Route to 1.1.1.1 (1.1.1.1)

 1  1.1.1.1          0.3 ms  loss 0%
```
**ping_the_route_gui:**

<img width="662" height="520" alt="image" src="https://github.com/user-attachments/assets/11a26184-f22f-4927-8c01-1ae601f1ada0" />

**ping_the_route_gui example input & output:**

<img width="662" height="520" alt="image" src="https://github.com/user-attachments/assets/10a2edb8-851d-4880-bc7c-d8397c729b25" />

(sorry for bad english)
