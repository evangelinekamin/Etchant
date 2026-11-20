# Etchant Circuit Gauntlet Expansion Prompt

Use this prompt with several frontier or open-weight models to generate new
PCB idea cases for `evals/pcb_ideas.yaml`. The goal is breadth, not flattering
the current codebase.

```text
You are helping expand Etchant, an open-source PCB-design agent. Generate a
diverse gauntlet of PCB design requests that would reveal what the agent can
and cannot build today.

Return YAML only, using this schema:

version: 1
cases:
  - id: short_snake_case_id
    title: Human-readable board title
    prompt: >
      Natural-language user request for the board.
    expected_maturity: fabrication_candidate | research_required | architecture_only | reject_or_escalate
    topology: known_topology_or_blank
    advisor_expected: optional_known_topology
    priority: optional_priority
    spec:
      input_voltage: number
      output_voltage: number
      output_current: number
    tags: [short, tags]
    notes:
      - Concrete risk, missing information, or validation need.

Known Etchant topologies today:
- buck_converter
- boost_converter
- ldo_regulator
- led_driver
- sensor_breakout
- mcu_breakout
- op_amp_buffer
- voltage_divider
- mosfet_switch
- usb_c_sink_protection
- brushed_motor_driver
- usb_nvme_bridge

Generate 20-40 cases with broad coverage. Include:
- Easy wins the current topology library should handle.
- Near misses that need one new topology, such as LiPo charging, high-side load
  switches, current-sense monitors, USB-UART, CAN/RS-485 transceivers,
  relay/solenoid drivers, audio preamps, isolated DC/DC, and LED matrices.
- Hard or dangerous requests that should be marked architecture_only or
  reject_or_escalate, such as mains AC, high-current battery packs, RF radios,
  DDR/high-speed memory, PCIe/NVMe bridges, and medical/safety-critical boards.
- At least five cases where the correct response is "ask for missing
  requirements" rather than inventing values.
- At least five cases that prioritize JLCPCB Basic Parts / SMT assembly.

Do not overfit to the listed topologies. If a case needs a topology that does
not exist, leave topology blank and explain the missing topology in notes.
Do not invent exact IC choices unless they are common, defensible, and the
case notes say the part must still be verified against datasheets and layout
guidelines.
```
