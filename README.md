## This fork: the car in a simulator

Simantic's fork of HyTech Racing's firmware monorepo, with a `sim/` directory that runs the real firmware in the Simantic simulator.
**Licence:** the upstream repository carries no LICENSE file (GitHub reports none), so nothing here is a licence grant. Only `sim/`
and this section are added; nothing is offered to or published at upstream. Based on upstream `develop` at a84cb75 (`main` has moved
on; the sim-only patches apply to that commit, not to current `main`). Details: [sim/README.md](sim/README.md).

**What runs** (`sim` 0.10.0 build f219eb31, 2026-11-15, guest time bounded, all on the unmodified production envs plus 5 sim patches):

| Board | MCU | Result |
| --- | --- | --- |
| ACU | Teensy 4.1 (i.MX RT1062) | boots; reads its LTC6811 chain stand-ins; drives CAN2/CAN3 |
| CCU | Teensy 4.1 | boots; ILI9341 on LPSPI4; reaches charging, `CHARGER_CONTROL` 530 V / 0.2 A seen by the charger stand-in at 6.849 s |
| Dashboard | STM32H750 | runs 3 s without a fault in the car scenario; screen contents not inspected: `unverified` |
| VCF, VCR | Teensy 4.1 | **do not boot on this sim**: BusFault, see gaps |

**Scenario** (`sim graph --scenario sim/scenarios/car/charge.yaml`, ADC pads omitted). The whole-car graph (`car.yaml`) adds VCF, VCR and the Dashboard:

```mermaid
flowchart LR
  acu["acu<br/>Teensy41"]
  acu_mux(["mux<br/>SPI.SPIMultiplexer"])
  acu -- "lpspi3" --- acu_mux
  acu_chain0(["chain0<br/>SPI.ScriptedSpiSlave"])
  acu -- "mux 0x0" --- acu_chain0
  acu_chain1(["chain1<br/>SPI.ScriptedSpiSlave"])
  acu -- "mux 0x1" --- acu_chain1
  acu_adcmux(["adcmux<br/>SPI.SPIMultiplexer"])
  acu -- "lpspi4" --- acu_adcmux
  acu_adc0(["adc0<br/>SPI.ScriptedSpiSlave"])
  acu -- "adcmux 0x0" --- acu_adc0
  acu_em(["em<br/>CAN.ScriptedCanNode"])
  ccu["ccu<br/>Teensy41"]
  ccu_tft(["tft<br/>SPI.ScriptedSpiSlave"])
  ccu -- "lpspi4" --- ccu_tft
  ccu_stim(["stim<br/>Scripted.ScriptedGpioPeer"])
  ccu -- "sysbus" --- ccu_stim
  ccu_charger(["charger<br/>CAN.ScriptedCanNode"])
  ccu_mon(["mon<br/>CAN.ScriptedCanNode"])
  medium0{{"can"}}
  acu -- "can2" --- medium0
  ccu -- "can1" --- medium0
  ccu_mon --- medium0
  medium1{{"can"}}
  acu -- "can3" --- medium1
  acu_em --- medium1
  medium2{{"can"}}
  ccu -- "can3" --- medium2
  ccu_charger --- medium2
```

**Configurations tried:**

| Configuration | Where | Virtual | Wall | Result |
| --- | --- | --- | --- | --- |
| ACU + CCU + energy meter + charger | `charge` | 7 s | 100 s | runs; ACU 58.8 MIPS, CCU 38.8 MIPS; charger sees 530 V / 0.2 A at 6.849 s |
| Whole car, 5 boards | `car` | 3 s | 58 s | ACU, CCU, Dashboard run; VCF and VCR end in BusFault; 2110 lines on the main bus log |
| VCR alone (ready-to-drive plan) | `vcr-rtd` | 2 s | 11 s | VCR ends in BusFault at boot, no USB output |

The original author's 11 s whole-car drive cycle (600 s wall) was not re-run here: `unverified`.

**Gaps, with the evidence:**
- VCF and VCR: `FAIL: machine 'vcf' ended in BusFault at pc=0x0001382e (tempmonGetTemp)`, same for `vcr` at 0x0001680e, faulting pc in `analog_init` (Teensy core temperature-monitor read). Reproduced on the VCR alone. A model gap in the released `sim` (the i.MX RT1062 TEMPMON block is in the engine source but not in this release, `unverified` whether newer builds boot); not worked around.
- ACU and CCU: `[bus] unhandled write: 0x400c4044`, once per run, no visible effect.
- Dashboard needs `rcc: hseFrequency: 25000000` in its board file, otherwise FDCAN drops every 1 Mbit frame.
- The CCU stand-in display reports `missing_end_trailer` diagnostics from the display peer.

**Run it** (needs `sim`, PlatformIO, rsync, Python 3):

```sh
export SIM=$(which sim)
sim/build.sh
sim/run.sh charge charge-1 7
sim/run.sh car car-1 3
```

**Changes to the firmware** (applied to a copy by `sim/build.sh`, listed in `sim/patches/`): 0001 CCU display on hardware SPI; 0002 CCU debug print enabled;
0003 Dashboard init call and typo (real bug); 0004 VCF `Wire2.begin()` (real bug); 0005 sim-only fixed EEPROM calibration for VCF.

Everything below is HyTech Racing's README.

---

# HyTech Racing Monorepo

This repository contains the firmware for all HyTech Racing boards in a single, centralized codebase. Each board maintains its own directory and build configuration, preserving the separation of individual projects while enabling shared libraries, consistent tooling, and streamlined development.

## Boards

| Board | Description |
| ------ | ----------- |
| **ACU** | Accumulator Control Unit |
| **CCU** | Charger Control Unit |
| **Dashboard** | Driver Dashboard |
| **VCF** | Vehicle Controller Front |
| **VCR** | Vehicle Controller Rear |
| **RDC** | Driverless Controller |

## Documentation

For more information about the monorepo, including:

- Why we transitioned to a monorepo
- Repository organization and coding conventions
- Firmware flashing procedures
- CI/CD workflows
- And much more!

see the HyTech Racing Wiki:

<https://wiki.hytechracing.org/books/ht11-design/page/monorepo-documentation>