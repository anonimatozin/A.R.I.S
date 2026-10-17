import random
import statistics

from aris_eyes.eyes.animator import EyeAnimator, IdleSettings, Spring
from aris_eyes.eyes.presets import MOOD_ORDER, PRESETS, Mood, parse_mood

DT = 1 / 60


def run(anim, seconds, dt=DT):
    frame, frames = None, []
    for _ in range(int(seconds / dt)):
        frame = anim.update(dt)
        frames.append(frame)
    return frame, frames


def test_mola_converge_sem_explodir_mesmo_com_quadro_lento():
    s = Spring(0.0, 260.0, 0.7)
    s.target = 1.0
    for _ in range(40):
        s.step(0.1)                         # quadro de 100 ms
    assert abs(s.x - 1.0) < 1e-3


def test_cada_expressao_chega_ao_alvo():
    for mood in MOOD_ORDER:
        anim = EyeAnimator(IdleSettings(saccades=False, breathing=False), Mood.NEUTRAL, random.Random(1))
        anim.set_mood(mood)
        frame, _ = run(anim, 3.0)
        preset = PRESETS[mood]
        assert abs(frame.lid_bottom - preset.target("lid_bottom")) < 0.03, mood
        assert abs(frame.lid_slant - preset.target("lid_slant")) < 0.03, mood
        assert abs(frame.x_mix - preset.target("x_mix")) < 0.03, mood


def test_pisca_e_volta_a_abrir():
    anim = EyeAnimator(IdleSettings(blink_min_s=0.5, blink_max_s=1.0), rng=random.Random(2))
    _, frames = run(anim, 6.0)
    opens = [f.open for f in frames]
    assert min(opens) < 0.15                # fechou
    assert opens[-1] > 0.0 and max(opens) > 0.95


def test_dormindo_e_erro_nao_piscam():
    for mood in (Mood.SLEEPING, Mood.ERROR):
        anim = EyeAnimator(IdleSettings(blink_min_s=0.3, blink_max_s=0.4), mood, random.Random(3))
        _, frames = run(anim, 5.0)
        assert max(f.open for f in frames) - min(f.open for f in frames) < 0.02, mood


def test_olhadas_aleatorias_movem_o_olhar_e_podem_ser_desligadas():
    on = EyeAnimator(IdleSettings(saccades=True), rng=random.Random(4))
    _, frames = run(on, 20.0)
    assert statistics.pstdev(f.gx for f in frames) > 0.05
    off = EyeAnimator(IdleSettings(saccades=False), rng=random.Random(4))
    _, frames = run(off, 20.0)
    assert max(abs(f.gx) for f in frames) < 0.01


def test_look_at_segura_e_depois_solta():
    anim = EyeAnimator(IdleSettings(saccades=False), rng=random.Random(5))
    anim.look_at(0.8, -0.5, hold=1.0)
    frame, _ = run(anim, 0.8)
    assert frame.gx > 0.6 and frame.gy < -0.3
    frame, _ = run(anim, 3.0)
    assert abs(frame.gx) < 0.05


def test_falando_pulsa_e_aceita_volume_externo():
    anim = EyeAnimator(IdleSettings(breathing=False), Mood.SPEAKING, random.Random(6))
    _, frames = run(anim, 4.0)
    assert max(f.h for f in frames) - min(f.h for f in frames) > 8      # pulsa
    anim.set_speech_level(0.0)
    frame, _ = run(anim, 1.0)
    assert abs(frame.h - PRESETS[Mood.SPEAKING].target("h")) < 3        # silencio = parado
    anim.set_speech_level(1.0)
    frame, _ = run(anim, 1.0)
    assert frame.h > PRESETS[Mood.SPEAKING].target("h") + 20            # volume maximo = olho maior


def test_apelidos_em_portugues():
    assert parse_mood("pensando") is Mood.THINKING
    assert parse_mood("FALANDO") is Mood.SPEAKING
    assert parse_mood("idle") is Mood.NEUTRAL
    assert parse_mood("nao-existe") is None


def test_valores_do_frame_ficam_em_faixas_seguras():
    anim = EyeAnimator(rng=random.Random(7))
    for mood in MOOD_ORDER:
        anim.set_mood(mood)
        for f in run(anim, 2.0)[1]:
            assert 0.0 <= f.open <= 1.3 and 0.0 <= f.lid_top <= 0.95 and 0.0 <= f.x_mix <= 1.0
            assert f.w > 0 and f.h > 0


def test_so_repinta_quando_a_mudanca_e_visivel():
    from aris_eyes.eyes.animator import Frame
    from aris_eyes.ui.eyes_widget import frames_differ
    a = Frame()
    assert not frames_differ(a, Frame(h=a.h + 0.05))        # menos de 1 pixel: nao repinta
    assert frames_differ(a, Frame(h=a.h + 1.0))
    assert frames_differ(a, Frame(gx=0.05))
