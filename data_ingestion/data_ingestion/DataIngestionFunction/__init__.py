"""
Azure Function App for Data Ingestion
Monitors Azure Blob Storage for new or updated files and performs data ingestion into Azure AI Search.
Runs on a timer schedule (every 30 minutes by default).
Uses managed identity for secure access to Azure resources.
"""

import logging
import azure.functions as func
import asyncio
import sys
import os

# Add parent directory to path to import data_ingestion_function_app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_ingestion_function_app import main as run_ingestion_job

# Configure logging
logger = logging.getLogger("azure.functions.DataIngestionFunction")


async def main_async(timer: func.TimerRequest) -> None:
    """Async wrapper for the ingestion job."""
    logger.info("Data Ingestion Function triggered")
    
    if timer.past_due:
        logger.warning("Timer is past due! Running anyway.")
    
    try:
        # Run the ingestion job
        await run_ingestion_job()
        logger.info("Data ingestion completed successfully")
    except Exception as e:
        logger.error(f"Data ingestion failed: {e}", exc_info=True)
        raise


def main(timer: func.TimerRequest) -> None:
    """Entry point for Azure Function."""
    asyncio.run(main_async(timer))
