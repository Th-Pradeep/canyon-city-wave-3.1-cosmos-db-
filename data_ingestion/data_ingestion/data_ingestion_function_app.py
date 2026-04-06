"""
Containerized Data Ingestion Job for Azure Search OpenAI RAG
This script monitors Azure Blob Storage for new or updated files and performs data ingestion.
Designed to run as a scheduled Azure Container App job.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient
from openai import AsyncOpenAI
from rich.logging import RichHandler

# Import prepdocslib modules
sys.path.append(str(Path(__file__).parent / "prepdocslib"))

from prepdocslib.blobmanager import BlobManager
from prepdocslib.filestrategy import FileStrategy
from prepdocslib.integratedvectorizerstrategy import IntegratedVectorizerStrategy
from prepdocslib.listfilestrategy import ADLSGen2ListFileStrategy, File, ListFileStrategy
from prepdocslib.servicesetup import (
    OpenAIHost,
    build_file_processors,
    clean_key_if_exists,
    setup_blob_manager,
    setup_embeddings_service,
    setup_figure_processor,
    setup_image_embeddings_service,
    setup_openai_client,
    setup_search_info,
)
from prepdocslib.strategy import DocumentAction, Strategy

logger = logging.getLogger("ingestion-job")


def clean_env_value(value: str) -> str:
    """Remove surrounding quotes from environment variable values."""
    if value and isinstance(value, str):
        value = value.strip()
        # Remove surrounding quotes (both single and double)
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
    return value


class BlobStorageMonitor:
    """Monitors Azure Blob Storage for new or updated files."""

    def __init__(
        self,
        storage_account: str,
        container_name: str,
        credential: AsyncTokenCredential,
        state_file: str = "/tmp/last_sync.json",
        lookback_hours: int = 24,
        state_blob_container: str = None,
    ):
        self.storage_account = storage_account
        self.container_name = container_name
        self.credential = credential
        self.state_file = state_file
        self.lookback_hours = lookback_hours
        self.state_blob_container = state_blob_container or container_name
        self.state_blob_name = ".ingestion_state/last_sync.json"
        self.blob_service_client: Optional[BlobServiceClient] = None

    async def initialize(self):
        """Initialize blob service client."""
        account_url = f"https://{self.storage_account}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)

    async def get_last_sync_time(self) -> datetime:
        """Get the last sync time from blob storage state, or use lookback hours."""
        try:
            # Try to load state from blob storage
            if self.blob_service_client:
                container_client = self.blob_service_client.get_container_client(self.state_blob_container)
                blob_client = container_client.get_blob_client(self.state_blob_name)
                
                try:
                    blob_data = await blob_client.download_blob()
                    content = await blob_data.readall()
                    state = json.loads(content.decode('utf-8'))
                    last_sync = datetime.fromisoformat(state.get("last_sync_time"))
                    logger.info(f"Last sync time from blob storage: {last_sync}")
                    return last_sync
                except Exception as e:
                    logger.info(f"No previous state found in blob storage: {e}")
        except Exception as e:
            logger.warning(f"Could not read state from blob storage: {e}")

        # Default to lookback hours
        lookback_time = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        logger.info(f"Using lookback time: {lookback_time} ({self.lookback_hours} hours)")
        return lookback_time
    
    async def get_tracked_blobs(self) -> list[str]:
        """Get list of blobs tracked in the last sync from blob storage."""
        try:
            if self.blob_service_client:
                container_client = self.blob_service_client.get_container_client(self.state_blob_container)
                blob_client = container_client.get_blob_client(self.state_blob_name)
                
                try:
                    blob_data = await blob_client.download_blob()
                    content = await blob_data.readall()
                    state = json.loads(content.decode('utf-8'))
                    tracked = state.get("tracked_blobs", [])
                    logger.info(f"Retrieved {len(tracked)} tracked blobs from storage")
                    return tracked
                except Exception as e:
                    logger.info(f"No previous tracked blobs found: {e}")
        except Exception as e:
            logger.warning(f"Could not read tracked blobs from blob storage: {e}")
        return []

    async def save_sync_time(self, sync_time: datetime, current_blobs: list[str] = None):
        """Save the current sync time and blob list to blob storage."""
        try:
            state = {
                "last_sync_time": sync_time.isoformat(),
                "last_run": datetime.now(timezone.utc).isoformat(),
                "tracked_blobs": current_blobs or []
            }
            
            # Save to blob storage for persistence across function executions
            if self.blob_service_client:
                container_client = self.blob_service_client.get_container_client(self.state_blob_container)
                blob_client = container_client.get_blob_client(self.state_blob_name)
                
                state_json = json.dumps(state, indent=2)
                await blob_client.upload_blob(state_json, overwrite=True)
                logger.info(f"Saved sync time to blob storage: {sync_time} with {len(current_blobs or [])} tracked blobs")
            else:
                logger.warning("BlobServiceClient not initialized, state not persisted")
        except Exception as e:
            logger.error(f"Failed to save state to blob storage: {e}")

    async def get_new_or_updated_blobs(self) -> tuple[list[str], list[str]]:
        """Get lists of blobs that are new/updated and deleted since last sync.
        
        Returns:
            tuple: (new_or_updated_blobs, deleted_blobs)
        """
        if not self.blob_service_client:
            raise RuntimeError("BlobServiceClient not initialized. Call initialize() first.")

        last_sync = await self.get_last_sync_time()
        previous_blobs = set(await self.get_tracked_blobs())
        container_client = self.blob_service_client.get_container_client(self.container_name)

        new_or_updated_blobs = []
        current_blobs = []
        current_time = datetime.now(timezone.utc)
        
        try:
            async for blob in container_client.list_blobs():
                blob_name = blob.name
                # Only process supported file types
                if self._is_supported_file(blob_name):
                    current_blobs.append(blob_name)
                    
                    # Check if blob was modified after last sync
                    if blob.last_modified and blob.last_modified.replace(tzinfo=timezone.utc) > last_sync:
                        new_or_updated_blobs.append(blob_name)
                        logger.info(
                            f"Found new/updated blob: {blob_name} (modified: {blob.last_modified})"
                        )

            # Detect deleted blobs
            current_blobs_set = set(current_blobs)
            deleted_blobs = list(previous_blobs - current_blobs_set)
            
            if deleted_blobs:
                logger.info(f"Detected {len(deleted_blobs)} deleted blobs: {deleted_blobs}")

            # Save current time and current blob list as state
            await self.save_sync_time(current_time, current_blobs)

        except Exception as e:
            logger.error(f"Error listing blobs: {e}")
            raise

        return new_or_updated_blobs, deleted_blobs

    @staticmethod
    def _is_supported_file(filename: str) -> bool:
        """Check if file type is supported for ingestion."""
        supported_extensions = {
            ".pdf",
            ".txt",
            ".md",
            ".html",
            ".htm",
            ".json",
            ".csv",
            ".docx",
            ".pptx",
            ".xlsx",
        }
        return any(filename.lower().endswith(ext) for ext in supported_extensions)

    async def close(self):
        """Close the blob service client."""
        if self.blob_service_client:
            await self.blob_service_client.close()


class BlobListFileStrategy(ListFileStrategy):
    """List file strategy that processes specific blobs from storage."""

    def __init__(
        self,
        blob_names: list[str],
        storage_account: str,
        container_name: str,
        credential: AsyncTokenCredential,
        enable_global_documents: bool = False,
    ):
        self.blob_names = blob_names
        self.storage_account = storage_account
        self.container_name = container_name
        self.credential = credential
        self.enable_global_documents = enable_global_documents
        self.blob_service_client: Optional[BlobServiceClient] = None

    async def list(self):
        """List the specific blob files to process."""
        logger.info(f"BlobListFileStrategy: Processing {len(self.blob_names)} blobs")
        account_url = f"https://{self.storage_account}.blob.core.windows.net"
        self.blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
        container_client = self.blob_service_client.get_container_client(self.container_name)

        for blob_name in self.blob_names:
            logger.info(f"BlobListFileStrategy: Processing blob: {blob_name}")
            try:
                blob_client = container_client.get_blob_client(blob_name)
                properties = await blob_client.get_blob_properties()

                # Download blob to temporary file
                temp_dir = Path("/tmp/ingestion_files")
                temp_dir.mkdir(exist_ok=True)
                temp_file = temp_dir / blob_name.replace("/", "_")

                async with blob_client:
                    with open(temp_file, "wb") as f:
                        stream = await blob_client.download_blob()
                        data = await stream.readall()
                        f.write(data)
                
                logger.info(f"BlobListFileStrategy: Downloaded to {temp_file} ({len(data)} bytes)")

                # Build ACLs
                acls = {}
                if self.enable_global_documents:
                    acls = {"oids": ["all"], "groups": ["all"]}

                # Yield File object
                yield File(content=open(temp_file, mode="rb"), acls=acls, url=blob_client.url)
                logger.info(f"BlobListFileStrategy: Yielded File object for {blob_name}")

            except Exception as e:
                logger.error(f"Error processing blob {blob_name}: {e}", exc_info=True)

    async def close(self):
        """Close the blob service client."""
        if self.blob_service_client:
            await self.blob_service_client.close()


async def check_search_service_connectivity(search_service: str) -> bool:
    """Check if the search service is accessible."""
    ping_url = f"https://{search_service}.search.windows.net/ping"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                return response.status == 200
    except Exception as e:
        logger.debug(f"Search service ping failed: {e}")
        return False


async def setup_azure_credential() -> AsyncTokenCredential:
    """Setup Azure credential based on environment."""
    # In Container Apps, use Managed Identity
    if os.getenv("AZURE_CLIENT_ID"):
        logger.info(f"Using Managed Identity with client ID: {os.getenv('AZURE_CLIENT_ID')}")
        return ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
    else:
        logger.info("Using DefaultAzureCredential")
        return DefaultAzureCredential()


async def delete_documents_from_index(
    deleted_blob_names: list[str],
    search_service: str,
    search_index: str,
    azure_credential: AsyncTokenCredential,
):
    """Delete documents from search index based on blob names."""
    if not deleted_blob_names:
        return
    
    from azure.search.documents.aio import SearchClient
    from azure.core.credentials import AzureKeyCredential
    
    logger.info(f"Deleting {len(deleted_blob_names)} documents from search index")
    
    search_endpoint = f"https://{search_service}.search.windows.net"
    
    async with SearchClient(
        endpoint=search_endpoint,
        index_name=search_index,
        credential=azure_credential
    ) as search_client:
        for blob_name in deleted_blob_names:
            try:
                # Search for documents matching this blob's source path
                # The sourcefile field typically contains the blob name
                results = await search_client.search(
                    search_text="",
                    filter=f"sourcefile eq '{blob_name}'",
                    select=["id"],
                    top=1000
                )
                
                doc_ids = []
                async for result in results:
                    doc_ids.append(result["id"])
                
                if doc_ids:
                    logger.info(f"Deleting {len(doc_ids)} document chunks for blob: {blob_name} from index")
                    # Delete documents by ID
                    await search_client.delete_documents(documents=[{"id": doc_id} for doc_id in doc_ids])
                else:
                    logger.warning(f"No document chunks found for deleted blob: {blob_name} in index")
                    
            except Exception as e:
                logger.error(f"Error deleting document chunks for blob {blob_name}: {e}", exc_info=True)


async def run_ingestion(
    blob_names: list[str],
    azure_credential: AsyncTokenCredential,
    force_reindex: bool = False,
):
    """Run the ingestion process for specified blobs."""
    # Get configuration from environment variables
    storage_account = clean_env_value(os.environ["AZURE_STORAGE_ACCOUNT"])
    storage_container = clean_env_value(os.environ["AZURE_STORAGE_CONTAINER"])
    storage_resource_group = clean_env_value(os.environ["AZURE_STORAGE_RESOURCE_GROUP"])
    subscription_id = clean_env_value(os.environ["AZURE_SUBSCRIPTION_ID"])
    search_service = clean_env_value(os.environ["AZURE_SEARCH_SERVICE"])
    search_index = clean_env_value(os.environ["AZURE_SEARCH_INDEX"])

    # Feature flags
    use_int_vectorization = os.getenv("USE_FEATURE_INT_VECTORIZATION", "").lower() == "true"
    use_multimodal = os.getenv("USE_MULTIMODAL", "").lower() == "true"
    use_acls = os.getenv("AZURE_USE_AUTHENTICATION", "").lower() == "true"
    enforce_access_control = os.getenv("AZURE_ENFORCE_ACCESS_CONTROL", "").lower() == "true"
    enable_global_documents = os.getenv("AZURE_ENABLE_GLOBAL_DOCUMENT_ACCESS", "").lower() == "true"
    dont_use_vectors = os.getenv("USE_VECTORS", "").lower() == "false"
    use_agentic_knowledgebase = os.getenv("USE_AGENTIC_KNOWLEDGEBASE", "").lower() == "true"
    use_content_understanding = os.getenv("USE_MEDIA_DESCRIBER_AZURE_CU", "").lower() == "true"

    OPENAI_HOST = OpenAIHost(clean_env_value(os.environ["OPENAI_HOST"]))

    # Validate configuration
    if use_agentic_knowledgebase and OPENAI_HOST not in [OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM]:
        raise Exception("Agentic retrieval requires an Azure OpenAI chat completion service")

    # Check search service connectivity
    is_connected = await check_search_service_connectivity(search_service)
    if not is_connected:
        logger.error("Unable to connect to Azure AI Search service")
        raise RuntimeError("Search service connectivity check failed")

    # Setup search info
    search_info = setup_search_info(
        search_service=search_service,
        index_name=search_index,
        use_agentic_knowledgebase=use_agentic_knowledgebase,
        knowledgebase_name=clean_env_value(os.getenv("AZURE_SEARCH_KNOWLEDGEBASE_NAME", "")),
        azure_openai_endpoint=clean_env_value(os.environ["AZURE_OPENAI_ENDPOINT"]),
        azure_openai_knowledgebase_deployment=clean_env_value(os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT", "")),
        azure_openai_knowledgebase_model=clean_env_value(os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_MODEL", "")),
        azure_credential=azure_credential,
        search_key=None,
        azure_vision_endpoint=clean_env_value(os.getenv("AZURE_VISION_ENDPOINT", "")),
    )

    # Setup blob manager
    blob_manager = setup_blob_manager(
        azure_credential=azure_credential,
        storage_account=storage_account,
        storage_container=storage_container,
        storage_resource_group=storage_resource_group,
        subscription_id=subscription_id,
        storage_key=None,
        image_storage_container=clean_env_value(os.environ.get("AZURE_IMAGESTORAGE_CONTAINER", "")),
    )

    # Setup list file strategy for specific blobs
    list_file_strategy = BlobListFileStrategy(
        blob_names=blob_names,
        storage_account=storage_account,
        container_name=storage_container,
        credential=azure_credential,
        enable_global_documents=enable_global_documents,
    )

    # Setup embeddings
    emb_model_dimensions = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "1536"))

    openai_client, azure_openai_endpoint = setup_openai_client(
        openai_host=OPENAI_HOST,
        azure_credential=azure_credential,
        azure_openai_service=clean_env_value(os.getenv("AZURE_OPENAI_SERVICE", "")),
        azure_openai_custom_url=clean_env_value(os.getenv("AZURE_OPENAI_CUSTOM_URL", "")),
        azure_openai_api_key=clean_env_value(os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE", "")),
        openai_api_key=None,
        openai_organization=clean_env_value(os.getenv("OPENAI_ORGANIZATION", "")),
    )

    openai_embeddings_service = None
    if not dont_use_vectors:
        openai_embeddings_service = setup_embeddings_service(
            OPENAI_HOST,
            openai_client,
            emb_model_name=clean_env_value(os.environ["AZURE_OPENAI_EMB_MODEL_NAME"]),
            emb_model_dimensions=emb_model_dimensions,
            azure_openai_deployment=clean_env_value(os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT", "")),
            azure_openai_endpoint=azure_openai_endpoint,
            disable_batch=False,
        )

    # Setup ingestion strategy
    ingestion_strategy: Strategy
    document_action = DocumentAction.Add

    if use_int_vectorization:
        if not openai_embeddings_service or OPENAI_HOST not in [OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM]:
            raise Exception("Integrated vectorization strategy requires an Azure OpenAI embeddings service")

        ingestion_strategy = IntegratedVectorizerStrategy(
            search_info=search_info,
            list_file_strategy=list_file_strategy,
            blob_manager=blob_manager,
            document_action=document_action,
            embeddings=openai_embeddings_service,
            search_field_name_embedding=clean_env_value(os.environ["AZURE_SEARCH_FIELD_NAME_EMBEDDING"]),
            subscription_id=subscription_id,
            search_analyzer_name=clean_env_value(os.getenv("AZURE_SEARCH_ANALYZER_NAME", "")),
            use_acls=use_acls,
            category=None,
            enforce_access_control=enforce_access_control,
        )
    else:
        # Build file processors
        file_processors = build_file_processors(
            azure_credential=azure_credential,
            document_intelligence_service=clean_env_value(os.getenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE", "")),
            document_intelligence_key=None,
            use_local_pdf_parser=clean_env_value(os.getenv("USE_LOCAL_PDF_PARSER", "")) == "true",
            use_local_html_parser=clean_env_value(os.getenv("USE_LOCAL_HTML_PARSER", "")) == "true",
            process_figures=use_multimodal,
        )

        figure_processor = setup_figure_processor(
            credential=azure_credential,
            use_multimodal=use_multimodal,
            use_content_understanding=use_content_understanding,
            content_understanding_endpoint=clean_env_value(os.getenv("AZURE_CONTENTUNDERSTANDING_ENDPOINT", "")),
            openai_client=openai_client,
            openai_model=clean_env_value(os.getenv("AZURE_OPENAI_CHATGPT_MODEL", "")),
            openai_deployment=clean_env_value(os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT", ""))
            if OPENAI_HOST == OpenAIHost.AZURE
            else None,
        )

        image_embeddings_service = setup_image_embeddings_service(
            azure_credential=azure_credential,
            vision_endpoint=clean_env_value(os.getenv("AZURE_VISION_ENDPOINT", "")),
            use_multimodal=use_multimodal,
        )

        ingestion_strategy = FileStrategy(
            search_info=search_info,
            list_file_strategy=list_file_strategy,
            blob_manager=blob_manager,
            file_processors=file_processors,
            document_action=document_action,
            embeddings=openai_embeddings_service,
            image_embeddings=image_embeddings_service,
            search_analyzer_name=clean_env_value(os.getenv("AZURE_SEARCH_ANALYZER_NAME", "")),
            search_field_name_embedding=clean_env_value(os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")),
            use_acls=use_acls,
            category=None,
            figure_processor=figure_processor,
            enforce_access_control=enforce_access_control,
            use_web_source=False,
            use_sharepoint_source=False,
        )

    try:
        # Setup index if needed (only on first run or if forced)
        if force_reindex:
            logger.info("Setting up search index...")
            await ingestion_strategy.setup()
            logger.info("Search index setup complete")

        # Run ingestion
        logger.info(f"Starting ingestion of {len(blob_names)} files...")
        logger.info(f"Files to process: {blob_names}")
        await ingestion_strategy.run()

        logger.info(f"Successfully ingested {len(blob_names)} files")

    finally:
        # Cleanup
        try:
            await blob_manager.close_clients()
            await openai_client.close()
            await list_file_strategy.close()
        except Exception as e:
            logger.debug(f"Failed to close async clients cleanly: {e}")


async def main():
    """Main entry point for the ingestion job."""
    # Get configuration from environment variables
    lookback_hours = int(os.getenv("INGESTION_LOOKBACK_HOURS", "24"))
    force_reindex = os.getenv("FORCE_REINDEX", "false").lower() == "true"
    verbose = os.getenv("VERBOSE_LOGGING", "false").lower() == "true"

    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
        level=log_level,
    )
    logger.setLevel(log_level)
    
    # Suppress HTTP request/response headers logging
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

    logger.info("Starting Data Ingestion Job")
    logger.info(f"Lookback hours: {lookback_hours}")

    try:
        # Setup Azure credential
        azure_credential = await setup_azure_credential()

        # Get required environment variables
        storage_account = clean_env_value(os.environ["AZURE_STORAGE_ACCOUNT"])
        storage_container = clean_env_value(os.environ["AZURE_STORAGE_CONTAINER"])

        # Monitor blob storage for new/updated files
        monitor = BlobStorageMonitor(
            storage_account=storage_account,
            container_name=storage_container,
            credential=azure_credential,
            lookback_hours=lookback_hours,
        )

        await monitor.initialize()

        # Get new or updated blobs and deleted blobs
        blob_names, deleted_blobs = await monitor.get_new_or_updated_blobs()
        
        # Handle deletions first
        if deleted_blobs:
            logger.info(f"Found {len(deleted_blobs)} deleted files to remove from index")
            search_service = clean_env_value(os.environ["AZURE_SEARCH_SERVICE"])
            search_index = clean_env_value(os.environ["AZURE_SEARCH_INDEX"])
            await delete_documents_from_index(
                deleted_blob_names=deleted_blobs,
                search_service=search_service,
                search_index=search_index,
                azure_credential=azure_credential,
            )
        
        # Handle additions/updates
        if not blob_names:
            if deleted_blobs:
                logger.info("No new or updated files found, but deletions were processed.")
            else:
                logger.info("No new, updated, or deleted files found. Nothing to process.")
            await monitor.close()
            await azure_credential.close()
            return

        logger.info(f"Found {len(blob_names)} new/updated files to process")

        # Run ingestion for new/updated blobs
        await run_ingestion(
            blob_names=blob_names,
            azure_credential=azure_credential,
            force_reindex=force_reindex,
        )

        await monitor.close()
        await azure_credential.close()

        logger.info("Ingestion job completed successfully")

    except Exception as e:
        logger.error(f"Ingestion job failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
