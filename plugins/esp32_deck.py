"""Plugin ESP32 Deck para A.R.I.S.

Intent handlers para controle do ESP32 via comandos de terminal.
Registra o módulo 'hardware' no registry.
"""

from modules.esp32_hardware import LEDColor, SystemState


def handle_hardware(action: str, params: dict, **ctx) -> str:
    """Handler principal do módulo hardware."""
    hw = ctx.get("hardware")
    if not hw:
        return "Hardware Manager não inicializado"

    # Status
    if action == "status":
        print(hw.format_status())
        return ""

    # Conectar
    elif action == "connect":
        result = hw.start()
        print(f"  {result}")
        return result

    # Desconectar
    elif action == "disconnect":
        hw.stop()
        print("  Hardware Manager desligado")
        return ""

    # Estado visual
    elif action == "state":
        state_name = params.get("state", "idle")
        try:
            state = SystemState(state_name)
            hw.set_state(state)
            print(f"  Estado alterado: {state_name}")
        except ValueError:
            print(f"  Estado inválido: {state_name}")
            print(f"  Válidos: {', '.join(s.value for s in SystemState)}")
        return ""

    # LED esquerdo
    elif action == "led_left":
        r = params.get("r", 0)
        g = params.get("g", 0)
        b = params.get("b", 0)
        brightness = params.get("brightness", 80)
        hw.set_left_led(LEDColor(r=r, g=g, b=b, brightness=brightness))
        print(f"  LED Esquerdo: RGB({r},{g},{b}) brilho={brightness}")
        return ""

    # LED direito
    elif action == "led_right":
        r = params.get("r", 0)
        g = params.get("g", 0)
        b = params.get("b", 0)
        brightness = params.get("brightness", 80)
        hw.set_right_led(LEDColor(r=r, g=g, b=b, brightness=brightness))
        print(f"  LED Direito: RGB({r},{g},{b}) brilho={brightness}")
        return ""

    # Ambos LEDs
    elif action == "led_both":
        r = params.get("r", 0)
        g = params.get("g", 0)
        b = params.get("b", 0)
        brightness = params.get("brightness", 80)
        hw.set_both_leds(LEDColor(r=r, g=g, b=b, brightness=brightness))
        print(f"  LEDs ambos: RGB({r},{g},{b}) brilho={brightness}")
        return ""

    # Efeito
    elif action == "effect":
        target = params.get("target", "both")
        effect = params.get("effect", "blink")
        hw.set_effect(target, effect)
        print(f"  Efeito '{effect}' em '{target}'")
        return ""

    # Desligar LEDs
    elif action == "leds_off":
        hw.turn_off_leds()
        print("  LEDs desligados")
        return ""

    # Flash
    elif action == "flash":
        flash_type = params.get("type", "success")
        if flash_type == "success":
            hw.flash_success()
        else:
            hw.flash_error()
        print(f"  Flash: {flash_type}")
        return ""

    # Heartbeat
    elif action == "heartbeat":
        hw._send_sync({"tipo": "heartbeat"})
        print("  Heartbeat enviado")
        return ""

    print(f"  Ação desconhecida: {action}")
    return ""


def register(registry):
    """Auto-registra o plugin no registry."""
    registry.register_intent(
        "hardware",
        description="Controle do hardware ESP32 (LEDs, botão, estados)"
    )
    registry._intent_handlers["hardware"] = handle_hardware
