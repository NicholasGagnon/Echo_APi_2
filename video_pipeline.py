import os
import time
import requests
from gtts import gTTS
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    TextClip,
    CompositeVideoClip,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def telecharger_video(video_url: str, destination: str) -> str:
    """Télécharge la vidéo générée par l'IA depuis son URL vers un fichier local."""
    print(f"⬇️  Téléchargement de la vidéo depuis {video_url[:80]}...")
    response = requests.get(video_url, stream=True)
    response.raise_for_status()
    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"✅ Vidéo téléchargée : {destination}")
    return destination


def generer_voix(texte: str, destination: str, langue: str = "fr", vitesse: float = 1.15) -> str:
    """Génère un fichier audio à partir d'un texte, en utilisant gTTS, puis accélère légèrement le débit."""
    print(f"🎙️  Génération de la voix pour : {texte[:60]}...")

    chemin_temp = destination.replace(".mp3", "_temp.mp3")
    tts = gTTS(text=texte, lang=langue, slow=False)
    tts.save(chemin_temp)

    # Accélère légèrement l'audio avec FFmpeg pour un débit plus naturel/dynamique
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-i", chemin_temp,
        "-filter:a", f"atempo={vitesse}",
        destination
    ], check=True, capture_output=True)

    os.remove(chemin_temp)
    print(f"✅ Voix générée (vitesse x{vitesse}) : {destination}")
    return destination


def trouver_police_disponible():
    """Cherche une police qui existe vraiment sur le système, dans l'ordre de préférence."""
    polices_a_essayer = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/verdana.ttf",
    ]
    for police in polices_a_essayer:
        if os.path.exists(police):
            print(f"🔤 Police trouvée : {police}")
            return police
    print("⚠️ Aucune police trouvée dans la liste, utilisation de la police par défaut de Pillow.")
    return None


def ajouter_texte_a_l_ecran(clip_video, segments_texte: list):
    """
    Ajoute des textes synchronisés par-dessus la vidéo.
    segments_texte est une liste de dicts :
    [{"texte": "Facture en 30 secondes", "debut": 0, "fin": 2}, ...]
    """
    police = trouver_police_disponible()

    clips_texte = []
    for segment in segments_texte:
        kwargs_texte = {
            "text": segment["texte"],
            "font_size": 50,
            "color": "white",
            "stroke_color": "black",
            "stroke_width": 2,
            "method": "caption",
            "size": (clip_video.w - 100, None),
        }
        if police:
            kwargs_texte["font"] = police

        txt_clip = (
            TextClip(**kwargs_texte)
            .with_position(("center", "bottom"))
            .with_start(segment["debut"])
            .with_duration(segment["fin"] - segment["debut"])
        )
        clips_texte.append(txt_clip)

    return CompositeVideoClip([clip_video] + clips_texte)


def assembler_video_finale(
    video_url: str,
    texte_narration: str,
    segments_texte: list,
    nom_fichier: str = None,
) -> str:
    """
    Pipeline complet :
    1. Télécharge la vidéo générée par l'IA
    2. Génère la voix-off à partir du texte de narration
    3. Superpose le texte synchronisé à l'écran
    4. Assemble tout (vidéo + voix) dans un seul fichier final
    Retourne le chemin du fichier final.
    """
    timestamp = int(time.time())
    nom_fichier = nom_fichier or f"video_finale_{timestamp}"

    chemin_video_brute = os.path.join(OUTPUT_DIR, f"{nom_fichier}_brute.mp4")
    chemin_audio = os.path.join(OUTPUT_DIR, f"{nom_fichier}_voix.mp3")
    chemin_final = os.path.join(OUTPUT_DIR, f"{nom_fichier}_final.mp4")

    # 1. Télécharger la vidéo
    telecharger_video(video_url, chemin_video_brute)

    # 2. Générer la voix
    generer_voix(texte_narration, chemin_audio)

    # 3. Charger la vidéo et l'audio
    print("🎬 Assemblage de la vidéo finale...")
    video_clip = VideoFileClip(chemin_video_brute)
    audio_clip = AudioFileClip(chemin_audio)

    # Si la voix est plus longue que la vidéo, on coupe à la durée la plus courte
    duree_finale = min(video_clip.duration, audio_clip.duration)
    video_clip = video_clip.subclipped(0, duree_finale)
    audio_clip = audio_clip.subclipped(0, duree_finale)

    # 4. Ajouter le texte synchronisé
    if segments_texte:
        video_avec_texte = ajouter_texte_a_l_ecran(video_clip, segments_texte)
    else:
        video_avec_texte = video_clip

    # 5. Assembler audio + vidéo
    video_finale = video_avec_texte.with_audio(audio_clip)

    # 6. Exporter
    video_finale.write_videofile(
        chemin_final,
        codec="libx264",
        audio_codec="aac",
        fps=video_clip.fps or 24,
    )

    # Nettoyage des fichiers intermédiaires
    video_clip.close()
    audio_clip.close()
    os.remove(chemin_video_brute)
    os.remove(chemin_audio)

    print(f"🎉 Vidéo finale prête : {chemin_final}")
    return chemin_final