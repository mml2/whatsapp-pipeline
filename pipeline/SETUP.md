# WhatsApp Contact Extraction Pipeline — Setup Guide

## Prerequisites
- Python 3.10+
- WhatsApp account with access to target group
- Anthropic API key

## Step 1 — Install WhatsApp MCP Server
Clone the MCP server repo and install dependencies:
  git clone https://github.com/lharries/whatsapp-mcp /Users/<you>/ml-whatsapp/mcp
  cd /Users/<you>/ml-whatsapp/mcp
  pip install -r requirements.txt

## Step 2 — Configure Read-Only Access
In config.yaml, set the following:
  permissions:
    read: true
    post: false
    leave_group: false
  target_group: "Wayne Desi Gals"

## Step 3 — Directory Structure
Keep all generated pipeline code in:
  /Users/<you>/ml-whatsapp/pipeline/

## Step 4 — Run Tests Before Deploying
  pytest pipeline/tests/ --cov=pipeline --cov-report=term-missing
  Target: 90% coverage minimum before any production run.

## Step 5 — Logging
Each pipeline stage must emit structured logs in this format:
  [STAGE][STATUS] message_id=<id> | detail=<detail>

Example:
  [CLASSIFY][OK]    message_id=101 | type=QUESTION | confidence=HIGH
  [THREAD][WARN]    message_id=104 | detail=no parent found, flagged for review
  [EXTRACT][OK]     message_id=107 | phone=+971501234567 | name=Ahmed
  [STORE][OK]       answer_id=A023 | linked_to=Q011
