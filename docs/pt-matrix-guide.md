# Filling the Packet Tracer capability matrix (P0 manual item)

**File to edit:** `netarch/data/pt_capabilities.yaml`, 17 rows. **Time:** about 45 minutes.
Each answer changes what the `pt` dialect generates: /31 or /30, which IPsec algorithms, and whether QoS is included. No code changes are needed afterwards.

## 1. Set up (5 min)
1. Open Packet Tracer 8.x and start a new file. Add three devices from the device palette:
   - **2911** router (Network Devices → Routers)
   - **3560-24PS** multilayer switch (Network Devices → Switches)
   - **2960-24TT** switch
   The devices don't need to be connected. You are only testing whether the CLI accepts each command.
2. **2911 only — enable the security licence** (needed for rows 12 and 13). Click the router → CLI:
   ```
   enable
   configure terminal
   license boot module c2900 technology-package securityk9
   ```
   Answer `yes`, then:
   ```
   end
   copy running-config startup-config
   reload
   ```
   After the reload, `show version` should list `securityk9` as enabled.
3. Write your PT version (Help → About) into the first row's `notes`.

## 2. How to judge each row
Paste the block into the device's CLI (start from `enable` mode). Then:

| You see | result | What to write |
|---|---|---|
| No error, and the line appears in `show running-config` | `accepted` | — |
| `% Invalid input detected`, `% Incomplete command`, `Bad mask`, or the line is missing from the running config | `rejected` | Copy the exact error into `notes` |
| The given syntax fails but a close variant works (e.g. `hash sha` instead of `hash sha256`) | `alternative` | Put the working syntax in `alternative:` and the error in `notes` |

If a row has several commands and only some fail, record the failing ones in `notes`. Mark the row `rejected`, or `alternative` if you found working syntax.

Example of a filled row:
```yaml
  - id: ipsec_sha256_group14
    ...
    result: alternative
    alternative: "hash sha / group 5 / esp-sha-hmac"
    notes: "PT 8.2.2: 'hash sha256' -> % Invalid input; 'group 14' -> % Invalid input"
```

## 3. The 17 rows
Start each block from `enable`.

### On the 3560-24PS (multilayer switch)
**1. trunk_encapsulation_dot1q**
```
configure terminal
interface fa0/1
 switchport trunk encapsulation dot1q
 switchport mode trunk
end
```
**2. rapid_pvst** (do this on the 3560 **and** on the 2960; it's accepted only if both accept it)
```
configure terminal
spanning-tree mode rapid-pvst
end
show spanning-tree summary
```
The summary should say `rapid-pvst`.

**3. routed_port_slash31_3560**
```
configure terminal
ip routing
interface gi0/1
 no switchport
 ip address 10.255.0.0 255.255.255.254
end
show ip interface brief
```
The address must show on Gi0/1.

**16. svi_extended_acl_log**
```
configure terminal
vlan 10
interface vlan 10
 ip address 10.0.10.1 255.255.255.0
exit
access-list 120 deny ip 10.0.20.0 0.0.0.255 10.0.99.0 0.0.0.255 log
access-list 120 permit ip any any
interface vlan 10
 ip access-group 120 in
end
```
**6. ospf_auto_cost_reference_bandwidth** (3560 part; the 2911 part is below)
```
configure terminal
router ospf 1
 auto-cost reference-bandwidth 10000
end
```

### On the 2911 router
**4. router_interface_slash31**
```
configure terminal
interface gi0/0
 ip address 10.255.0.0 255.255.255.254
 no shutdown
end
```
**5. dot1q_subinterfaces**
```
configure terminal
interface gi0/1.10
 encapsulation dot1Q 10
 ip address 10.0.10.1 255.255.255.0
end
```
**6. ospf_auto_cost_reference_bandwidth** (2911 part; accepted only if both devices accept it)
```
configure terminal
router ospf 1
 auto-cost reference-bandwidth 10000
end
```
**7. ospf_area_range**
```
configure terminal
router ospf 1
 network 10.0.0.0 0.0.255.255 area 1
 area 1 range 10.0.0.0 255.255.0.0
end
```
**8. ospf_hello_dead_timers**
```
configure terminal
interface gi0/1
 ip ospf hello-interval 1
 ip ospf dead-interval 4
end
```
**9. ebgp_neighbor_network_null0**
```
configure terminal
ip route 10.0.0.0 255.255.0.0 Null0
router bgp 65001
 neighbor 169.254.0.2 remote-as 64512
 network 10.0.0.0 mask 255.255.0.0
end
```
**10. prefix_list_route_map_redistribution**
```
configure terminal
ip prefix-list CLOUD seq 5 permit 172.31.0.0/16
route-map BGP-TO-OSPF permit 10
 match ip address prefix-list CLOUD
exit
router ospf 1
 redistribute bgp 65001 subnets route-map BGP-TO-OSPF
end
```
**11. gre_tunnel**
```
configure terminal
interface Tunnel0
 ip address 172.16.0.1 255.255.255.252
 tunnel source gi0/0
 tunnel destination 203.0.113.2
end
```
**15. tunnel_adjust_mss_ip_mtu** (after row 11)
```
configure terminal
interface Tunnel0
 ip mtu 1400
 ip tcp adjust-mss 1360
end
```
**12. ikev1_crypto_map** (needs securityk9 from setup step 2)
```
configure terminal
crypto isakmp policy 10
 encryption aes 256
 hash sha
 authentication pre-share
 group 5
exit
crypto isakmp key TESTKEY address 203.0.113.2
crypto ipsec transform-set TS esp-aes 256 esp-sha-hmac
exit
access-list 110 permit gre host 198.51.100.1 host 203.0.113.2
crypto map VPN 10 ipsec-isakmp
 set peer 203.0.113.2
 set transform-set TS
 match address 110
exit
interface gi0/0
 crypto map VPN
end
```
**13. ipsec_sha256_group14** (try each line; note exactly which ones fail)
```
configure terminal
crypto isakmp policy 20
 hash sha256
 group 14
exit
crypto ipsec transform-set TS2 esp-aes 256 esp-sha256-hmac
end
```
**14. mqc_llq**
```
configure terminal
class-map match-any TRADING
 match dscp ef
exit
policy-map WAN-OUT
 class TRADING
  priority 1000
 class class-default
  fair-queue
exit
exit
interface gi0/0
 service-policy output WAN-OUT
end
```

### On all three devices
**17. ssh_rsa_keys** (accepted only if all three accept it)
```
configure terminal
hostname T1
ip domain-name netarch.lab
crypto key generate rsa
```
Answer `2048` (or `1024` if 2048 is refused; note that in `notes`), then:
```
ip ssh version 2
username admin secret Admin123
line vty 0 4
 login local
 transport input ssh
end
```

## 4. When done
1. Make sure no row is left as `result: untested`.
2. Run `.venv/Scripts/python -m pytest -q tests/test_pt_capabilities.py`. It must pass.
3. Tick the P0 matrix item in `docs/implementation.md` and in `docs/testing.md`.
4. Optional: save the scratch file as `verification/pt-capabilities.pkt` as evidence.
