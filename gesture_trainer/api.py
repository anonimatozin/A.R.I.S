"""Integração futura com a ARIS (§18): evento GESTURE_DETECTED.

Publica no EventBus da ARIS quando disponível; sempre retorna o payload.
"""

import time


def gesture_payload(gesture, hand, confidence, position=None, movement=None):
    return {
        "gesture": gesture,
        "hand": hand,
        "confidence": round(float(confidence), 3),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "position": position or {},
        "movement": movement or {},
    }


def emit(gesture, hand, confidence, event_bus=None, **kw):
    payload = gesture_payload(gesture, hand, confidence, **kw)
    if event_bus is not None:
        try:
            from core.neural.events import Event
            event_bus.publish(Event(event_type="vision_gesture_detected",
                                    source="gesture_trainer", payload=payload,
                                    confidence=float(confidence)))
        except Exception:
            pass
    return payload
