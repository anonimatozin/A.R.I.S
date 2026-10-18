"""Testes das cenas (humor + props) e do SceneController. Sem Qt."""
import random

from aris_eyes.eyes.animator import EyeAnimator, IdleSettings
from aris_eyes.eyes.presets import MOOD_PROPS, PRESETS, Mood, parse_mood
from aris_eyes.eyes.props import PROP_NAMES, PropEngine
from aris_eyes.eyes.scenes import SCENE_ALIASES, SCENES, SceneController, resolve_scene, scene_names


def make(mood=Mood.NEUTRAL):
    anim = EyeAnimator(IdleSettings(saccades=False, breathing=False), mood, random.Random(1))
    eng = PropEngine(random.Random(2))
    return anim, eng, SceneController(anim, eng)


def tick(ctrl, eng, seconds, dt=1 / 60):
    for _ in range(int(seconds / dt)):
        ctrl.update(dt)
        eng.update(dt)


def test_toda_cena_usa_humor_e_props_validos():
    for name, scene in SCENES.items():
        assert scene.mood in PRESETS, name
        assert all(p in PROP_NAMES for p in scene.props), name
        if scene.accent:
            assert scene.accent.startswith("#") and len(scene.accent) == 7, name


def test_apelidos_resolvem_para_cenas_existentes():
    for alias, target in SCENE_ALIASES.items():
        assert target in SCENES, alias
        assert resolve_scene(alias) is SCENES[target]
    assert resolve_scene("SPOTIFY") is SCENES["spotify"]
    assert resolve_scene("nao-existe") is None
    assert resolve_scene("") is None
    assert "spotify" in scene_names() and "fone" in scene_names()


def test_play_liga_humor_e_props_da_cena():
    anim, eng, ctrl = make()
    assert ctrl.play("spotify") is True
    assert anim.mood is Mood.MUSIC
    assert eng.active_names() == {"notes", "equalizer"}
    assert ctrl.accent == "#1ed760" and ctrl.current == "spotify"


def test_cena_desconhecida_nao_muda_nada():
    anim, eng, ctrl = make(Mood.HAPPY)
    assert ctrl.play("xpto") is False
    assert anim.mood is Mood.HAPPY and not eng.active_names() and ctrl.current is None


def test_cena_com_tempo_volta_ao_humor_anterior():
    anim, eng, ctrl = make(Mood.THINKING)
    ctrl.play("apaixonado", 1.0)
    assert anim.mood is Mood.LOVE
    tick(ctrl, eng, 0.5)
    assert anim.mood is Mood.LOVE
    tick(ctrl, eng, 0.7)
    assert anim.mood is Mood.THINKING and ctrl.current is None
    assert eng.active_names() == set(MOOD_PROPS.get(Mood.THINKING, ()))


def test_duracao_explicita_vence_a_padrao_da_cena():
    anim, eng, ctrl = make()
    ctrl.play("apaixonado", 0.3)                      # padrao seria 6 s
    tick(ctrl, eng, 0.5)
    assert ctrl.current is None


def test_cena_sem_tempo_dura_ate_mandarem_parar():
    anim, eng, ctrl = make(Mood.NEUTRAL)
    ctrl.play("fone")
    tick(ctrl, eng, 30)
    assert ctrl.current == "fone" and anim.mood is Mood.CHILL
    ctrl.stop()
    assert anim.mood is Mood.NEUTRAL and not eng.active_names() and ctrl.accent is None


def test_trocar_cena_por_cena_guarda_o_humor_original():
    anim, eng, ctrl = make(Mood.SAD)
    ctrl.play("spotify")
    ctrl.play("fone")                                 # troca direto, sem passar pelo humor triste
    ctrl.stop()
    assert anim.mood is Mood.SAD


def test_set_mood_encerra_a_cena_e_liga_os_props_do_novo_humor():
    anim, eng, ctrl = make()
    ctrl.play("spotify")
    ctrl.set_mood(Mood.LOVE)
    assert ctrl.current is None and ctrl.accent is None
    assert anim.mood is Mood.LOVE
    assert eng.active_names() == {"eye_heart", "hearts"}
    ctrl.set_mood(Mood.NEUTRAL)
    assert eng.active_names() == set()


def test_stop_sem_cena_nao_faz_nada():
    anim, eng, ctrl = make(Mood.HAPPY)
    ctrl.stop()
    assert anim.mood is Mood.HAPPY


def test_cena_de_musica_faz_os_olhos_pulsarem_no_ritmo_e_solta_depois():
    anim, eng, ctrl = make()
    ctrl.play("spotify")
    tick(ctrl, eng, 2.0)
    assert anim._speech_external is not None
    ctrl.stop()
    assert anim._speech_external is None


def test_cena_sem_ritmo_nao_mexe_na_fala():
    anim, eng, ctrl = make()
    anim.set_speech_level(0.7)                        # volume vindo da fala real da ARIS
    ctrl.play("apaixonado")
    tick(ctrl, eng, 1.0)
    assert anim._speech_external == 0.7


def test_set_accent_manual():
    anim, eng, ctrl = make()
    ctrl.play("spotify")
    ctrl.set_accent("#aa00ff")
    assert ctrl.accent == "#aa00ff"
    ctrl.set_accent(None)
    assert ctrl.accent is None


def test_novos_humores_chegam_ao_alvo_e_tem_nome_em_portugues():
    for alias, mood in (("apaixonado", Mood.LOVE), ("piscadinha", Mood.WINK), ("fone", Mood.CHILL),
                        ("spotify", Mood.MUSIC), ("tonto", Mood.DIZZY), ("chorando", Mood.CRYING),
                        ("carregando", Mood.LOADING), ("timido", Mood.SHY)):
        assert parse_mood(alias) is mood
