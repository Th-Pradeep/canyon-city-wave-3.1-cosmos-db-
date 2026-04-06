"""
Video to Transcript Function
Event Grid trigger that transcribes video files using Azure Speech Service Batch API.
Converts video to MP3 audio format before transcription for codec compatibility and smaller file size.
Uploads sentence-level transcript with timestamps to the 'content' container.
"""

import logging
import json
import os
import time
import uuid
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import requests
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

# Import moviepy for video-to-audio conversion
try:
    from moviepy.editor import VideoFileClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    logging.warning("moviepy not available - video-to-MP3 conversion will be skipped")

logger = logging.getLogger("VideoTranscriptFunction")


def wait_for_batch_transcription(transcription_url: str, headers: dict, check_interval: int = 10, max_wait_time: int = 7200):
    """
    Poll the batch transcription status until it's complete.
    
    Args:
        transcription_url: URL to check transcription status
        headers: HTTP headers for authentication
        check_interval: Seconds between status checks (default: 10)
        max_wait_time: Maximum wait time in seconds (default: 7200 = 2 hours)
    
    Returns:
        Final status JSON when transcription succeeds
    
    Raises:
        Exception: If transcription fails or times out
    """
    elapsed_time = 0
    last_log_time = 0
    log_interval = 30  # Log every 30 seconds
    
    logger.info(f"   Starting batch transcription polling (max wait: {max_wait_time // 60} minutes)")
    
    while elapsed_time < max_wait_time:
        status_response = requests.get(transcription_url, headers=headers)
        status_response.raise_for_status()
        status = status_response.json()
        
        current_status = status.get('status', 'Unknown')
        
        if current_status == 'Succeeded':
            minutes, seconds = divmod(elapsed_time, 60)
            logger.info(f"   ✓ Batch transcription completed! Time: {int(minutes)}m {int(seconds)}s")
            return status
        elif current_status == 'Failed':
            error_msg = status.get('properties', {}).get('error', 'Unknown error')
            minutes, seconds = divmod(elapsed_time, 60)
            logger.error(f"   ❌ Batch transcription failed after {int(minutes)}m {int(seconds)}s: {error_msg}")
            raise Exception(f"Batch transcription failed: {error_msg}")
        else:
            # Log less frequently to reduce log noise
            if elapsed_time - last_log_time >= log_interval or elapsed_time == 0:
                minutes, seconds = divmod(elapsed_time, 60)
                hours, minutes = divmod(minutes, 60)
                time_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s" if hours > 0 else f"{int(minutes)}m {int(seconds)}s"
                logger.info(f"   Batch transcription status: {current_status} - Elapsed: {time_str}")
                last_log_time = elapsed_time
            
            time.sleep(check_interval)
            elapsed_time += check_interval
    
    minutes, seconds = divmod(max_wait_time, 60)
    hours, minutes = divmod(minutes, 60)
    time_str = f"{int(hours)}h {int(minutes)}m" if hours > 0 else f"{int(minutes)}m"
    raise Exception(f"Batch transcription timed out after {time_str}")


def convert_video_to_mp3(video_path: str, output_mp3_path: str) -> None:
    """
    Convert video file to MP3 audio format using moviepy.
    
    Args:
        video_path: Path to input video file
        output_mp3_path: Path to output MP3 file
    
    Raises:
        Exception: If moviepy is not available or conversion fails
    """
    if not MOVIEPY_AVAILABLE:
        raise Exception("moviepy library is required for video-to-MP3 conversion. Install with: pip install moviepy")
    
    logger.info(f"   Converting video to MP3 format...")
    logger.info(f"   Input: {video_path}")
    logger.info(f"   Output: {output_mp3_path}")
    
    try:
        # Load video file
        logger.info(f"   Loading video file...")
        video_clip = VideoFileClip(video_path)
        
        # Extract audio
        logger.info(f"   Extracting audio from video...")
        audio_clip = video_clip.audio
        
        if audio_clip is None:
            raise Exception("Video file has no audio track")
        
        # Write audio to MP3 file
        # Parameters: bitrate='128k' (good quality for speech, much smaller than WAV)
        logger.info(f"   Writing MP3 file (128 kbps, optimized for speech)...")
        audio_clip.write_audiofile(
            output_mp3_path,
            bitrate='128k',  # 128 kbps - good balance between quality and size
            codec='libmp3lame',  # MP3 codec
            verbose=False,
            logger=None  # Suppress moviepy's own logging
        )
        
        # Clean up
        audio_clip.close()
        video_clip.close()
        
        # Check output file size
        mp3_size = os.path.getsize(output_mp3_path)
        logger.info(f"   ✓ MP3 file created: {mp3_size / (1024*1024):.2f} MB")
        
    except Exception as e:
        logger.error(f"   ❌ Video-to-MP3 conversion failed: {e}")
        raise


def batch_transcribe_audio(blob_uri: str, source_language: str, speech_endpoint: str, speech_key: str, api_version: str = "2024-11-15") -> dict:
    """
    Use Azure Speech Service Batch Transcription API to transcribe audio/video file.
    
    Args:
        blob_uri: Direct URL to blob (can be SAS URL or use managed identity)
        source_language: Language code (e.g., 'en-US')
        speech_endpoint: Speech service endpoint URL
        speech_key: Speech service API key
        api_version: API version (default: 2024-11-15)
    
    Returns:
        Parsed transcript JSON with detailed results
    """
    # Construct API endpoint
    url = f"{speech_endpoint}/speechtotext/transcriptions:submit?api-version={api_version}"
    
    headers = {
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': speech_key,
    }
    
    payload = {
        "displayName": f"Video transcription {uuid.uuid4()}",
        "locale": source_language,
        "contentUrls": [blob_uri],
        "properties": {
            "wordLevelTimestampsEnabled": True,
            "displayFormWordLevelTimestampsEnabled": True,
            "punctuationMode": "DictatedAndAutomatic",
            "profanityFilterMode": "Masked",
            "timeToLiveHours": 48
        }
    }
    
    logger.info(f"   Submitting batch transcription request...")
    logger.info(f"   API Endpoint: {url}")
    logger.info(f"   Locale: {source_language}")
    logger.info(f"   Blob URI (first 100 chars): {blob_uri[:100]}...")
    logger.info(f"   Blob URI contains SAS: {'sig=' in blob_uri}")
    logger.info(f"   Request Payload: {json.dumps({**payload, 'contentUrls': ['<REDACTED>']}, indent=2)}")
    
    response = requests.post(url, json=payload, headers=headers)
    
    # Log detailed error information if request fails (non-2xx status codes)
    if response.status_code < 200 or response.status_code >= 300:
        logger.error(f"   ❌ Speech Service API Error:")
        logger.error(f"   Status Code: {response.status_code}")
        logger.error(f"   Response Headers: {dict(response.headers)}")
        try:
            error_body = response.json()
            logger.error(f"   Error Response Body: {json.dumps(error_body, indent=2)}")
        except:
            logger.error(f"   Error Response Text: {response.text}")
    
    response.raise_for_status()
    transcription_url = response.json()['self']
    
    logger.info(f"   ✓ Batch job submitted successfully")
    logger.info(f"   Job URL: {transcription_url[:80]}...")
    
    # Wait for completion
    final_status = wait_for_batch_transcription(transcription_url, headers)
    
    # Get transcription results
    files_url = final_status['links']['files']
    logger.info(f"   Downloading transcription results...")
    
    files_response = requests.get(files_url, headers=headers)
    files_response.raise_for_status()
    
    # Find the transcription content file
    files_json = files_response.json()
    content_url = None
    for file_info in files_json.get('values', []):
        if file_info.get('kind') == 'Transcription':
            content_url = file_info['links']['contentUrl']
            break
    
    if not content_url:
        raise Exception("No transcription content found in batch results")
    
    # Download transcript content (SAS URL - no auth header needed)
    logger.info(f"   Downloading transcript content...")
    content_response = requests.get(content_url)
    content_response.raise_for_status()
    transcript_json = content_response.json()
    
    logger.info(f"   ✓ Transcription results downloaded successfully")
    
    return transcript_json


def parse_batch_results(transcript_json: dict, video_name: str) -> str:
    """
    Parse batch transcription results into sentence-level format with timestamps.
    
    Args:
        transcript_json: Raw JSON from batch transcription API
        video_name: Original video filename
    
    Returns:
        Formatted JSON string with sentence-level transcripts and timestamps
    """
    # Extract sentence-level results with timestamps
    # IMPORTANT: Sort by timestamp first to ensure chronological order before deduplication
    recognized_phrases = sorted(
        transcript_json.get('recognizedPhrases', []),
        key=lambda x: parse_pt_duration(x.get('offset', 'PT0S'))
    )
    sentences = []
    seen_sentences = set()  # Track unique sentences to prevent Speech API duplicates
    
    for phrase in recognized_phrases:
        # Get the best (first) transcription result
        if phrase.get('nBest') and len(phrase['nBest']) > 0:
            best_result = phrase['nBest'][0]
            text = best_result.get('display', '')
            
            if text:  # Only include non-empty segments
                # Parse offset and duration (format: "PT0.52S" = 0.52 seconds)
                offset_str = phrase.get('offset', 'PT0S')
                duration_str = phrase.get('duration', 'PT0S')
                
                # Convert PT format to seconds
                offset_seconds = parse_pt_duration(offset_str)
                duration_seconds = parse_pt_duration(duration_str)
                end_seconds = offset_seconds + duration_seconds
                
                # Deduplication: Speech API sometimes returns duplicate phrases with slightly different timestamps
                # Use text + rounded start time (to nearest 0.1s) as unique key
                dedup_key = (text, round(offset_seconds, 1))
                
                if dedup_key not in seen_sentences:
                    seen_sentences.add(dedup_key)
                    
                    sentence = {
                        'text': text,
                        'start_time': format_timestamp_from_seconds(offset_seconds),
                        'end_time': format_timestamp_from_seconds(end_seconds),
                        'duration': format_timestamp_from_seconds(duration_seconds)
                    }
                    sentences.append(sentence)
    
    # Generate video URL based on filename pattern
    # URL pattern: https://www.reliatrax.com/post/{video-stem}
    # Example: "time-clock.mp4" -> "https://www.reliatrax.com/post/time-clock"
    video_stem = Path(video_name).stem  # Remove .mp4 extension
    video_url = f"https://www.reliatrax.com/post/{video_stem}"
    
    # Format final transcript
    transcript_data = {
        'video_file': video_name,
        'video_url': video_url,
        'language': 'en-US',
        'sentences': sentences,
        'total_sentences': len(sentences)
    }
    
    logger.info(f"   ✓ Parsed {len(sentences)} sentences from batch results")
    
    return json.dumps(transcript_data, indent=2)


def parse_pt_duration(pt_string: str) -> float:
    """
    Parse ISO 8601 duration format (PT format) to seconds.
    Examples: 'PT0.52S' -> 0.52, 'PT1M30.5S' -> 90.5, 'PT1H2M3S' -> 3723
    """
    import re
    
    if not pt_string or pt_string == 'PT0S':
        return 0.0
    
    # Remove 'PT' prefix
    duration = pt_string.replace('PT', '')
    
    hours = 0
    minutes = 0
    seconds = 0.0
    
    # Match hours (e.g., '1H')
    hour_match = re.search(r'(\d+)H', duration)
    if hour_match:
        hours = int(hour_match.group(1))
    
    # Match minutes (e.g., '30M')
    min_match = re.search(r'(\d+)M', duration)
    if min_match:
        minutes = int(min_match.group(1))
    
    # Match seconds (e.g., '45.5S')
    sec_match = re.search(r'([\d.]+)S', duration)
    if sec_match:
        seconds = float(sec_match.group(1))
    
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds


def format_timestamp_from_seconds(seconds: float) -> str:
    """
    Convert seconds to readable timestamp.
    Returns format: HH:MM:SS.mmm
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def generate_sas_url(blob_url: str, storage_account_name: str) -> str:
    """
    Generate a SAS URL for a blob to allow Azure Speech Service to access it.
    
    Args:
        blob_url: The original blob URL (e.g., https://account.blob.core.windows.net/container/blob.mp4)
        storage_account_name: Name of the storage account
    
    Returns:
        Blob URL with SAS token appended (properly URL-encoded)
    """
    from urllib.parse import unquote, quote
    
    # Parse container and blob name from URL
    # URL format: https://account.blob.core.windows.net/container/blob.mp4
    url_parts = blob_url.split(f"{storage_account_name}.blob.core.windows.net/", 1)
    if len(url_parts) != 2:
        raise ValueError(f"Invalid blob URL format: {blob_url}")
    
    path = url_parts[1]  # e.g., "video/canyon-city-sample.mp4" or "video/First%20Monday.mp4"
    # URL-decode the path to get actual blob name for SAS generation
    path = unquote(path)
    path_parts = path.split('/', 1)
    container_name = path_parts[0]
    blob_name = path_parts[1] if len(path_parts) > 1 else ""
    
    logger.info(f"   Generating SAS token for: {container_name}/{blob_name}")
    
    # Use managed identity to get storage account key
    credential = DefaultAzureCredential()
    account_url = f"https://{storage_account_name}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
    
    # Get the account key (required for SAS generation)
    # Note: This requires the function's managed identity to have proper permissions
    try:
        # Get user delegation key (for managed identity SAS)
        key_start_time = datetime.utcnow() - timedelta(minutes=5)
        key_expiry_time = datetime.utcnow() + timedelta(hours=2)
        user_delegation_key = blob_service_client.get_user_delegation_key(
            key_start_time=key_start_time,
            key_expiry_time=key_expiry_time
        )
        
        # Generate SAS token using user delegation key
        # Note: permission must be a string ("r" for read), not BlobSasPermissions object
        sas_token = generate_blob_sas(
            account_name=storage_account_name,
            container_name=container_name,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission="r",  # Read permission
            expiry=datetime.utcnow() + timedelta(hours=3),  # Extended to 3 hours for longer transcriptions
            start=datetime.utcnow() - timedelta(minutes=5)  # Allow for clock skew
        )
        
        # Reconstruct URL with properly encoded blob path
        # Use quote() to encode spaces and special characters for HTTP URL
        encoded_blob_path = f"{container_name}/{quote(blob_name, safe='')}"
        base_url = f"https://{storage_account_name}.blob.core.windows.net/{encoded_blob_path}"
        sas_url = f"{base_url}?{sas_token}"
        
        expiry_time = datetime.utcnow() + timedelta(hours=3)
        logger.info(f"   ✓ SAS token generated successfully")
        logger.info(f"   SAS expires at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')} UTC (in 3 hours)")
        return sas_url
        
    except Exception as e:
        logger.error(f"   ❌ Failed to generate SAS token: {e}")
        logger.error(f"   Make sure the function's managed identity has 'Storage Blob Delegator' role")
        raise


def main(eventGridEvent: func.EventGridEvent):
    """
    Triggered by Event Grid when a video file is uploaded to the 'video' container.
    
    Process:
    1. Extract blob info from Event Grid event
    2. Download video from blob
    3. Extract audio (using moviepy)
    4. Transcribe using Azure Speech Service with timestamps
    5. Upload transcript JSON to 'content' container
    """
    import time
    start_time = time.time()
    
    # Extract blob information from Event Grid event
    # EventGridEvent has properties: id, topic, subject, event_type, event_time
    # get_json() returns the 'data' portion of the event
    event_data = eventGridEvent.get_json()
    
    # Get event properties from EventGridEvent object (not from data)
    subject = eventGridEvent.subject  # /blobServices/default/containers/video/blobs/blobname.mp4
    event_type = eventGridEvent.event_type  # Microsoft.Storage.BlobCreated
    blob_url = event_data.get('url', '')  # This is in the data portion
    
    logger.info(f"="*60)
    logger.info(f"🎬 VIDEO TRANSCRIPTION STARTED (Event Grid Trigger)")
    logger.info(f"Event Type: {event_type}")
    logger.info(f"Subject: {subject}")
    logger.info(f"Blob URL: {blob_url}")
    logger.info(f"="*60)
    
    # Extract container and blob name from subject
    # subject format: /blobServices/default/containers/video/blobs/myvideo.mp4
    if not subject or '/blobs/' not in subject:
        logger.error(f"❌ Invalid subject format (missing /blobs/): {subject}")
        return
    
    # Split by /blobs/ to separate container path from blob name
    subject_parts = subject.split('/blobs/')
    if len(subject_parts) != 2:
        logger.error(f"❌ Could not parse blob path from subject: {subject}")
        return
    
    # URL-decode the blob name (Event Grid subjects have URL-encoded names)
    from urllib.parse import unquote
    blob_name = unquote(subject_parts[1])  # e.g., "canyon-city-sample.mp4" or "First Monday w_ Mike_ Time Clock.mp4"
    
    # Extract container name from first part
    container_part = subject_parts[0]  # /blobServices/default/containers/video
    container_name = container_part.split('/containers/')[-1]  # "video"
    
    video_name = blob_name.split('/')[-1]  # Handle nested paths
    
    logger.info(f"Container: {container_name}")
    logger.info(f"Blob name: {blob_name}")
    logger.info(f"Video name: {video_name}")
    
    # Get content length from event data
    content_length = event_data.get('contentLength', 0)
    logger.info(f"Blob size: {content_length} bytes ({content_length / (1024*1024):.2f} MB)")
    
    # Check if file is a supported video format
    SUPPORTED_VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg'}
    file_extension = Path(video_name).suffix.lower()
    
    logger.info(f"📄 File extension: {file_extension}")
    
    if file_extension not in SUPPORTED_VIDEO_EXTENSIONS:
        logger.warning(f"="*60)
        logger.warning(f"⚠️  SKIPPED - Not a video file")
        logger.warning(f"File: {video_name}")
        logger.warning(f"Extension: {file_extension}")
        logger.warning(f"Supported formats: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}")
        logger.warning(f"="*60)
        return  # Exit gracefully without error
    
    logger.info(f"✓ Video format supported: {file_extension}")
    
    try:
        # Get storage account name from blob URL
        # URL format: https://stuaxsjqhqm7d56.blob.core.windows.net/video/myvideo.mp4
        storage_account_name = blob_url.split('//')[1].split('.')[0]
        
        logger.info(f"Storage account: {storage_account_name}")
        
        # Get Speech Service configuration
        speech_key = os.environ.get("AZURE_SPEECH_KEY")
        speech_region = os.environ.get("AZURE_SPEECH_REGION", "eastus")
        speech_endpoint = os.environ.get("AZURE_SPEECH_ENDPOINT")
        
        if not speech_endpoint:
            speech_endpoint = f"https://{speech_region}.api.cognitive.microsoft.com"
        
        logger.info(f"Speech Service endpoint: {speech_endpoint}")
        logger.info(f"Speech Region: {speech_region}")
        logger.info(f"Speech Key: {'✓ Set' if speech_key else '✗ Not set'}")
        
        if not speech_key:
            logger.error("❌ AZURE_SPEECH_KEY environment variable not set")
            raise ValueError("AZURE_SPEECH_KEY environment variable not set")
        
        # IDEMPOTENCY & RACE CONDITION PREVENTION
        # Use a two-phase check:
        # 1. Check if transcript already exists (completed processing)
        # 2. Check if a .processing marker exists (currently being processed by another instance)
        # 3. Create .processing marker immediately to claim the work
        
        content_container = os.environ.get("dataStorageContainerName", "content")
        transcript_name = f"{Path(video_name).stem}_transcript.json"
        processing_marker_name = f"{Path(video_name).stem}.processing"
        
        logger.info(f"🔍 Checking processing status...")
        logger.info(f"   Transcript: {content_container}/{transcript_name}")
        logger.info(f"   Lock marker: {content_container}/{processing_marker_name}")
        
        try:
            credential = DefaultAzureCredential()
            account_url = f"https://{storage_account_name}.blob.core.windows.net"
            blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
            
            transcript_blob = blob_service_client.get_blob_client(
                container=content_container,
                blob=transcript_name
            )
            
            processing_marker_blob = blob_service_client.get_blob_client(
                container=content_container,
                blob=processing_marker_name
            )
            
            # Check 1: Is transcript already complete?
            if transcript_blob.exists():
                logger.warning(f"="*60)
                logger.warning(f"⚠️  SKIPPED - Transcript already exists")
                logger.warning(f"File: {video_name}")
                logger.warning(f"Transcript: {transcript_name}")
                logger.warning(f"This video was already processed.")
                logger.warning(f"="*60)
                return  # Exit gracefully - transcript already processed
            
            # Check 2 & 3: Atomically create processing marker (prevents race conditions)
            # Using if_none_match="*" ensures this fails if blob already exists
            # This is THE FIX for the duplicate transcription issue!
            logger.info(f"   ✓ No existing transcript found")
            logger.info(f"   🔒 Attempting to acquire processing lock (atomic operation)...")
            
            try:
                processing_marker_blob.upload_blob(
                    data=json.dumps({
                        "video_file": video_name,
                        "started_at": datetime.utcnow().isoformat(),
                        "function_invocation_id": eventGridEvent.id
                    }),
                    overwrite=False,  # Don't overwrite if exists
                    if_none_match="*"  # Atomic: only create if doesn't exist (prevents race!)
                )
                logger.info(f"   ✓ Processing lock acquired - proceeding with transcription")
            except Exception as lock_error:
                # ResourceExistsError means another instance already claimed this video
                if "BlobAlreadyExists" in str(lock_error) or "The specified blob already exists" in str(lock_error):
                    logger.warning(f"="*60)
                    logger.warning(f"⚠️  SKIPPED - Another instance claimed this video first")
                    logger.warning(f"File: {video_name}")
                    logger.warning(f"Lock marker: {processing_marker_name}")
                    logger.warning(f"This is a duplicate Event Grid event - handled by atomic lock.")
                    logger.warning(f"="*60)
                    return  # Exit gracefully - lost the race, another instance is processing
                else:
                    # Different error - re-raise
                    raise
            
        except Exception as e:
            logger.warning(f"   ⚠️  Could not perform idempotency check: {e}")
            logger.warning(f"   Proceeding with transcription anyway...")
        
        # STEP 1: Download video and convert to MP3
        logger.info(f"🎬 STEP 1/3: Downloading video and converting to MP3...")
        logger.info(f"   Feature: Video-to-MP3 conversion for codec compatibility and smaller file size")
        
        # Create temp directory for processing
        temp_dir = tempfile.mkdtemp()
        video_temp_path = None
        mp3_temp_path = None
        mp3_blob_url_with_sas = None
        
        try:
            # Download video to temp file
            video_temp_path = os.path.join(temp_dir, f"video_{uuid.uuid4().hex[:8]}{Path(video_name).suffix}")
            logger.info(f"   Downloading video to: {video_temp_path}")
            
            download_start = time.time()
            blob_client = blob_service_client.get_blob_client(
                container="video",
                blob=blob_name
            )
            
            with open(video_temp_path, 'wb') as video_file:
                video_data = blob_client.download_blob()
                video_file.write(video_data.readall())
            
            video_size_mb = os.path.getsize(video_temp_path) / (1024 * 1024)
            download_time = time.time() - download_start
            logger.info(f"   ✓ Video downloaded: {video_size_mb:.2f} MB in {download_time:.2f}s")
            
            # Convert video to MP3
            mp3_temp_path = os.path.join(temp_dir, f"audio_{uuid.uuid4().hex[:8]}.mp3")
            conversion_start = time.time()
            
            convert_video_to_mp3(video_temp_path, mp3_temp_path)
            
            mp3_size_mb = os.path.getsize(mp3_temp_path) / (1024 * 1024)
            conversion_time = time.time() - conversion_start
            logger.info(f"   ✓ Conversion completed in {conversion_time:.2f}s")
            logger.info(f"   Size reduction: {video_size_mb:.2f} MB → {mp3_size_mb:.2f} MB ({((video_size_mb - mp3_size_mb) / video_size_mb * 100):.1f}% smaller)")
            
            # Upload MP3 to audio container
            logger.info(f"   Uploading MP3 to 'audio' container...")
            audio_container = "audio"
            mp3_blob_name = f"{Path(video_name).stem}.mp3"
            
            # Ensure audio container exists
            try:
                audio_container_client = blob_service_client.get_container_client(audio_container)
                if not audio_container_client.exists():
                    logger.info(f"   Creating 'audio' container...")
                    audio_container_client.create_container()
            except Exception as container_error:
                logger.warning(f"   Container check/create error: {container_error}")
            
            upload_start = time.time()
            audio_blob_client = blob_service_client.get_blob_client(
                container=audio_container,
                blob=mp3_blob_name
            )
            
            with open(mp3_temp_path, 'rb') as mp3_file:
                audio_blob_client.upload_blob(mp3_file, overwrite=True)
            
            upload_time = time.time() - upload_start
            logger.info(f"   ✓ MP3 uploaded in {upload_time:.2f}s: {audio_container}/{mp3_blob_name}")
            
            # Generate SAS URL for MP3 file
            mp3_blob_url = audio_blob_client.url
            logger.info(f"   Generating SAS URL for MP3 file...")
            logger.info(f"   MP3 blob URL: {mp3_blob_url}")
            
            try:
                mp3_blob_url_with_sas = generate_sas_url(mp3_blob_url, storage_account_name)
                logger.info(f"   ✓ SAS URL generated for audio file")
                
                # Validate SAS URL format
                if '?' in mp3_blob_url_with_sas and 'sig=' in mp3_blob_url_with_sas:
                    logger.info(f"   ✓ SAS URL format validated (contains signature)")
                    
                    # Verify the blob is accessible via SAS URL
                    logger.info(f"   Verifying MP3 blob accessibility via SAS URL...")
                    try:
                        # Make a HEAD request to verify accessibility
                        import requests
                        verify_response = requests.head(mp3_blob_url_with_sas, timeout=10)
                        if verify_response.status_code == 200:
                            logger.info(f"   ✓ MP3 blob is accessible via SAS URL")
                            content_length = verify_response.headers.get('Content-Length', 'unknown')
                            logger.info(f"   MP3 file size (via SAS): {content_length} bytes")
                        else:
                            logger.error(f"   ❌ MP3 blob returned status {verify_response.status_code}")
                            logger.error(f"   This indicates the SAS URL is not working correctly")
                            raise Exception(f"MP3 blob not accessible: HTTP {verify_response.status_code}")
                    except requests.exceptions.RequestException as verify_error:
                        logger.error(f"   ❌ Could not verify MP3 blob accessibility: {verify_error}")
                        raise
                else:
                    logger.warning(f"   ⚠️  SAS URL may be invalid (missing signature)")
                    raise Exception("SAS URL validation failed")
                    
            except Exception as sas_error:
                logger.error(f"   ❌ MP3 SAS URL generation/validation failed: {sas_error}")
                logger.error(f"   Common causes:")
                logger.error(f"     1. Managed identity missing 'Storage Blob Delegator' role")
                logger.error(f"     2. Storage account permissions issue")
                logger.error(f"     3. Network connectivity issue")
                logger.info(f"   Falling back to direct video transcription...")
                raise  # This will trigger the fallback mechanism
            
        except Exception as conversion_error:
            logger.error(f"   ❌ Video-to-MP3 conversion failed: {conversion_error}")
            logger.info(f"   Falling back to direct video transcription...")
            # Clean up temp files
            if video_temp_path and os.path.exists(video_temp_path):
                os.remove(video_temp_path)
            if mp3_temp_path and os.path.exists(mp3_temp_path):
                os.remove(mp3_temp_path)
            if temp_dir and os.path.exists(temp_dir):
                os.rmdir(temp_dir)
            # Fall back to original video URL
            mp3_blob_url_with_sas = None
        
        # STEP 2: Submit batch transcription job
        logger.info(f"🎙️  STEP 2/3: Submitting batch transcription job...")
        logger.info(f"   Note: Batch transcription is asynchronous and may take several minutes")
        logger.info(f"   depending on file size and service load.")
        
        transcribe_start = time.time()
        
        # Use MP3 URL if conversion succeeded, otherwise use original video URL
        if mp3_blob_url_with_sas:
            logger.info(f"   Using converted MP3 audio file for transcription")
            logger.info(f"   MP3 URL length: {len(mp3_blob_url_with_sas)} characters")
            logger.info(f"   Container: audio, Blob: {Path(video_name).stem}.mp3")
            transcription_url = mp3_blob_url_with_sas
        else:
            logger.info(f"   Using original video file for transcription (conversion skipped)")
            # Generate SAS URL for the original blob
            logger.info(f"   Generating SAS URL for original video blob...")
            transcription_url = generate_sas_url(blob_url, storage_account_name)
            logger.info(f"   Video URL length: {len(transcription_url)} characters")
        
        # Submit and wait for batch transcription
        transcript_json = batch_transcribe_audio(
            blob_uri=transcription_url,
            source_language="en-US",
            speech_endpoint=speech_endpoint,
            speech_key=speech_key
        )
        
        transcribe_time = time.time() - transcribe_start
        logger.info(f"✓ Batch transcription completed in {transcribe_time:.2f}s")
        
        # Clean up temporary files
        try:
            if video_temp_path and os.path.exists(video_temp_path):
                os.remove(video_temp_path)
                logger.info(f"   ✓ Cleaned up temp video file")
            if mp3_temp_path and os.path.exists(mp3_temp_path):
                os.remove(mp3_temp_path)
                logger.info(f"   ✓ Cleaned up temp MP3 file")
            if temp_dir and os.path.exists(temp_dir):
                os.rmdir(temp_dir)
                logger.info(f"   ✓ Cleaned up temp directory")
        except Exception as cleanup_error:
            logger.warning(f"   ⚠️  Could not clean up temp files: {cleanup_error}")
        
        # Parse batch results into sentence format
        logger.info(f"   Parsing batch results into sentence format...")
        transcript = parse_batch_results(transcript_json, video_name)
        
        # Log transcript preview
        transcript_obj = json.loads(transcript)
        logger.info(f"   Total sentences: {transcript_obj.get('total_sentences', 0)}")
        if transcript_obj.get('full_text'):
            preview = transcript_obj['full_text'][:100]
            logger.info(f"   Preview: {preview}...")
        
        # STEP 3: Upload to content container
        upload_start = time.time()
        logger.info(f"⬆️  STEP 3/3: Uploading transcript to content container...")
        upload_transcript_to_content(video_name, transcript)
        upload_time = time.time() - upload_start
        logger.info(f"✓ Upload completed in {upload_time:.2f}s")
        
        # CLEANUP: Remove processing marker file (unlock)
        try:
            logger.info(f"🧹 Cleaning up processing lock marker...")
            processing_marker_blob.delete_blob()
            logger.info(f"   ✓ Processing lock released")
        except Exception as cleanup_error:
            logger.warning(f"   ⚠️  Could not delete processing marker: {cleanup_error}")
            logger.warning(f"   This won't affect functionality - marker will be ignored since transcript exists.")
        
        # Summary
        total_time = time.time() - start_time
        logger.info(f"="*60)
        logger.info(f"✅ PROCESSING COMPLETE - {video_name}")
        logger.info(f"⏱️  Total time: {total_time:.2f}s")
        logger.info(f"   - Video download & MP3 conversion: {(conversion_time if mp3_blob_url_with_sas else 0):.2f}s")
        logger.info(f"   - Batch transcription: {transcribe_time:.2f}s")
        logger.info(f"   - Upload: {upload_time:.2f}s")
        logger.info(f"   Processing method: {'MP3 Audio Transcription' if mp3_blob_url_with_sas else 'Direct Video Transcription'}")
        logger.info(f"="*60)
            
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"="*60)
        logger.error(f"❌ PROCESSING FAILED - {video_name}")
        logger.error(f"⏱️  Failed after: {total_time:.2f}s")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"="*60, exc_info=True)
        
        # CLEANUP: Remove processing marker on error so video can be retried
        try:
            logger.info(f"🧹 Cleaning up processing lock marker after error...")
            if 'processing_marker_blob' in locals():
                processing_marker_blob.delete_blob()
                logger.info(f"   ✓ Processing lock released - video can be retried")
        except Exception as cleanup_error:
            logger.warning(f"   ⚠️  Could not delete processing marker: {cleanup_error}")
        
        raise


def upload_transcript_to_content(video_name: str, transcript_json: str):
    """Upload transcript JSON to the 'content' container."""
    # Get configuration from environment
    storage_account = os.environ.get("dataStorageAccountName")
    content_container = os.environ.get("dataStorageContainerName", "content")
    
    logger.info(f"   Checking storage configuration...")
    logger.info(f"   Storage account: {storage_account if storage_account else '✗ Not set'}")
    logger.info(f"   Target container: {content_container}")
    
    if not storage_account:
        logger.error("   ❌ dataStorageAccountName environment variable not set")
        raise ValueError("dataStorageAccountName environment variable not set")
    
    logger.info(f"   Connecting to storage account: {storage_account}")
    
    # Use managed identity
    credential = DefaultAzureCredential()
    account_url = f"https://{storage_account}.blob.core.windows.net"
    blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
    
    # Create transcript filename: video.mp4 -> video_transcript.json
    transcript_name = f"{Path(video_name).stem}_transcript.json"
    transcript_size = len(transcript_json.encode('utf-8'))
    
    logger.info(f"   Transcript filename: {transcript_name}")
    logger.info(f"   Transcript size: {transcript_size / 1024:.2f} KB")
    
    # Upload to content container
    blob_client = blob_service_client.get_blob_client(
        container=content_container,
        blob=transcript_name
    )
    
    logger.info(f"   Uploading to blob: {content_container}/{transcript_name}")
    blob_client.upload_blob(transcript_json, overwrite=True)
    
    # Get blob URL
    blob_url = blob_client.url
    logger.info(f"   ✓ Transcript uploaded successfully")
    logger.info(f"   Blob URL: {blob_url}")
