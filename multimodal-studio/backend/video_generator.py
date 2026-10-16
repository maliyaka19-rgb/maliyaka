"""
Video Generation Module - Frame-based approach using free Pollinations.ai Image API
Ücretsiz görsel API ile frame üretip moviepy ile videoya birleştirir.
"""

import os
import time
import asyncio
import logging
import httpx
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
from io import BytesIO

from PIL import Image

logger = logging.getLogger("video-gen")

# Free Pollinations image API
POLLINATIONS_IMAGE_URL = "https://image.pollinations.ai/prompt/{prompt}"

# Generated videos directory
VIDEOS_DIR = os.path.join(os.path.dirname(__file__), "generated_videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)


class VideoGenerator:
    """Frame tabanlı video üretim sınıfı (ücretsiz Pollinations image API)."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0)

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        width: int = 1280,
        height: int = 720,
        fps: int = 24,
        num_frames: int = 8,
        style: str = "cinematic"
    ) -> Dict[str, Any]:
        """
        Metinden video üretir.

        Yöntem: Ücretsiz görsel API ile sahne frame'leri üretir,
        aralarına yumuşak geçişler (crossfade) ekleyip moviepy ile birleştirir.

        Args:
            prompt: Video açıklaması
            duration: Video süresi (saniye)
            width: Genişlik
            height: Yükseklik
            fps: Frame rate
            num_frames: Üretilecek sahne frame sayısı
            style: Görsel stil (cinematic, anime, realistic vb.)

        Returns:
            Dict với video URL ve metadata
        """
        start_time = time.time()

        try:
            # Generate frames concurrently
            frames = await self._generate_frames(
                prompt=prompt,
                num_frames=num_frames,
                width=width,
                height=height,
                style=style
            )

            if not frames:
                return {
                    "success": False,
                    "error": "No frames could be generated"
                }

            logger.info(f"Generated {len(frames)} frames, stitching video...")

            # Stitch frames into video with crossfade
            video_path = os.path.join(VIDEOS_DIR, f"vid_{int(time.time())}.mp4")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._create_video_from_frames,
                frames,
                video_path,
                duration,
                fps,
                width,
                height
            )

            duration_taken = time.time() - start_time
            video_id = os.path.basename(video_path)

            # Get file size
            file_size = os.path.getsize(video_path)

            return {
                "success": True,
                "video_id": video_id,
                "video_url": f"/api/v1/videos/{video_id}",
                "local_path": video_path,
                "prompt": prompt,
                "style": style,
                "width": width,
                "height": height,
                "duration": duration,
                "fps": fps,
                "num_frames": num_frames,
                "size_bytes": file_size,
                "generation_time": round(duration_taken, 2),
                "generated_at": datetime.utcnow().isoformat(),
                "source": "pollinations.ai (free frames)"
            }

        except Exception as e:
            logger.error(f"Video generation failed: {str(e)}")
            return {
                "success": False,
                "error": f"Video generation failed: {str(e)}",
                "generation_time": round(time.time() - start_time, 2)
            }

    async def _generate_frames(
        self,
        prompt: str,
        num_frames: int,
        width: int,
        height: int,
        style: str
    ) -> List[np.ndarray]:
        """Ücretsiz API ile SIRALI frame üretir (rate-limit koruması)."""
        # Style suffix
        style_suffix = {
            "cinematic": "cinematic lighting, film grain, professional color grading, dramatic composition",
            "realistic": "photorealistic, high detail, natural lighting",
            "anime": "anime style, vibrant colors, studio ghibli inspired",
            "artistic": "artistic painting, impressionist style, rich colors",
            "minimal": "minimalist, clean, simple composition",
        }.get(style, "cinematic lighting, professional quality")

        # Frame variations - her frame hafif farklı perspektif
        variations = [
            "wide establishing shot",
            "medium shot with slight zoom",
            "close-up detail shot",
            "dynamic angle shot",
            "panoramic view",
            "low angle dramatic shot",
            "overhead bird eye view",
            "intimate shallow depth of field",
        ]

        frames = []
        consecutive_fails = 0

        for i in range(num_frames):
            variation = variations[i % len(variations)]
            frame_prompt = f"{prompt}, {variation}, {style_suffix}"
            encoded = frame_prompt.replace(" ", "%20").replace(",", "%2C").replace("'", "")

            url = (
                f"https://image.pollinations.ai/prompt/{encoded}"
                f"?width={width}&height={height}&nologo=true&seed={i * 7 + 42}"
            )

            frame = None
            for attempt in range(3):  # 3 retry with backoff (faster fallback)
                try:
                    resp = await self.client.get(url, follow_redirects=True)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        img = Image.open(BytesIO(resp.content)).convert("RGB")
                        img = img.resize((width, height), Image.LANCZOS)
                        frame = np.array(img)
                        break
                    elif resp.status_code == 402:
                        # Rate limited - wait longer
                        wait = 2 * (attempt + 1)
                        logger.info(f"Frame {i}: rate limited (402), waiting {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        logger.warning(f"Frame {i} attempt {attempt+1}: status {resp.status_code}")
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Frame {i} attempt {attempt+1} failed: {e}")
                    await asyncio.sleep(2)

            if frame is not None:
                frames.append(frame)
                consecutive_fails = 0
                # Small delay between successful frames to avoid rate limit
                await asyncio.sleep(0.5)
            else:
                consecutive_fails += 1
                logger.warning(f"Frame {i} failed after all retries")
                # If too many consecutive fails, stop trying
                if consecutive_fails >= 2:
                    logger.error("Too many consecutive failures, stopping")
                    break

        logger.info(f"Generated {len(frames)}/{num_frames} frames")

        # Fallback: if no frames, create procedural frames
        if not frames:
            logger.info("No frames from API, creating procedural fallback frames")
            frames = self._create_fallback_frames(prompt, num_frames, width, height)

        return frames

    def _create_fallback_frames(
        self,
        prompt: str,
        num_frames: int,
        width: int,
        height: int
    ) -> List[np.ndarray]:
        """API başarısız olduğunda prosedürel frame'ler oluşturur (gradient animation)."""
        frames = []
        # Prompt'dan renk türet
        import hashlib
        hash_val = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
        base_h = (hash_val % 360)
        
        for i in range(num_frames):
            # Animated gradient
            img = Image.new("RGB", (width, height))
            pixels = img.load()
            hue_shift = (i / num_frames) * 60  # Gentle hue rotation
            
            for y in range(0, height, 4):  # Every 4th pixel for speed
                for x in range(0, width, 4):
                    import colorsys
                    h = ((base_h + hue_shift + x / width * 30) % 360) / 360
                    s = 0.5 + 0.3 * (y / height)
                    v = 0.3 + 0.4 * (x / width)
                    r, g, b = colorsys.hsv_to_rgb(h, s, v)
                    # Fill 4x4 block
                    for dy in range(4):
                        for dx in range(4):
                            if x + dx < width and y + dy < height:
                                pixels[x + dx, y + dy] = (int(r * 255), int(g * 255), int(b * 255))
            
            frames.append(np.array(img))
        
        return frames

    def _create_video_from_frames(
        self,
        frames: List[np.ndarray],
        output_path: str,
        target_duration: int,
        fps: int,
        width: int,
        height: int
    ):
        """Frame'leri crossfade geçişlerle videoya birleştirir."""
        from moviepy import ImageClip, concatenate_videoclips, CompositeVideoClip, vfx

        num_frames = len(frames)
        if num_frames == 0:
            raise ValueError("No frames to stitch")

        # Her frame'in süresi
        frame_duration = target_duration / num_frames

        # If only 1 frame, create a simple Ken Burns zoom video
        if num_frames == 1:
            clip = ImageClip(frames[0]).with_duration(target_duration)
            # Slow zoom in
            clip = clip.resized(lambda t: 1 + 0.05 * (t / target_duration))
            clip = clip.cropped(x_center=width / 2, y_center=height / 2, width=width, height=height)
            clip.write_videofile(
                output_path,
                fps=fps,
                codec="libx264",
                audio=False,
                preset="medium",
                logger=None
            )
            clip.close()
            return

        # Crossfade süresi (frame süresinin %30'u, min 0.3s)
        crossfade = max(0.3, frame_duration * 0.3)

        clips = []
        for i, frame_array in enumerate(frames):
            clip = ImageClip(frame_array).with_duration(frame_duration + crossfade)
            # Add slight zoom (Ken Burns effect) for motion
            if i % 2 == 0:
                clip = clip.resized(lambda t: 1 + 0.02 * t / (frame_duration + crossfade))
            else:
                clip = clip.resized(lambda t: 1.02 - 0.02 * t / (frame_duration + crossfade))

            # Crossfade in/out
            if i > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(crossfade)])
            if i < num_frames - 1:
                clip = clip.with_effects([vfx.CrossFadeOut(crossfade)])

            clips.append(clip)

        # Concatenate with crossfade
        if len(clips) > 1:
            final = concatenate_videoclips(clips, method="compose", padding=-crossfade)
        else:
            final = clips[0]

        # Crop to exact size (zoom effect may have changed size)
        final = final.cropped(x_center=width / 2, y_center=height / 2, width=width, height=height)

        # Write video
        final.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio=False,
            preset="medium",
            logger=None
        )

        final.close()

    async def close(self):
        """HTTP client'ı kapat."""
        await self.client.aclose()


# Global instance
_video_generator = None


def get_video_generator() -> VideoGenerator:
    """Video generator singleton instance'ını al."""
    global _video_generator
    if _video_generator is None:
        _video_generator = VideoGenerator()
    return _video_generator
