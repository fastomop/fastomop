#!/bin/bash
# FastOMOP Management Script
# Convenient commands for managing the FastOMOP container

COMPOSE_FILE="docker-compose.yml"

show_usage() {
    echo "FastOMOP Management Script"
    echo ""
    echo "Usage: ./manage.sh [command] [options]"
    echo ""
    echo "Commands:"
    echo "  start              Start the web interface"
    echo "  stop               Stop all containers"
    echo "  restart            Restart the web interface"
    echo "  status             Show container status"
    echo "  logs               Show live logs"
    echo "  logs-tail          Show last 50 lines of logs"
    echo "  shell              Open bash shell in web container"
    echo "  python             Open Python REPL in container"
    echo "  test               Run interactive CLI mode"
    echo "  bootstrap          Initialize prompts and knowledge base"
    echo "  batch <file>       Run batch processing on queries file"
    echo "  eval [options]     Run imaging VQA evaluation"
    echo "  rebuild            Rebuild and restart container"
    echo "  health             Check health status"
    echo "  stats              Show resource usage"
    echo "  backup             Create backup of data"
    echo "  clean              Remove container and volumes"
    echo ""
    echo "Examples:"
    echo "  ./manage.sh start                          # Start web interface"
    echo "  ./manage.sh test                           # Run interactive mode"
    echo "  ./manage.sh batch queries.json             # Process batch queries"
    echo "  ./manage.sh eval --split test --limit 100  # Run VQA eval (test split, 100 Qs)"
    echo "  ./manage.sh eval --mode team --limit 10    # Full pipeline eval (10 Qs)"
    echo "  ./manage.sh bootstrap                      # First-time setup"
    echo ""
}

case "$1" in
    start)
        echo "Starting FastOMOP web interface..."
        docker compose up -d web
        echo "✓ Started"
        docker compose ps
        ;;

    stop)
        echo "Stopping FastOMOP..."
        docker compose down
        echo "✓ Stopped"
        ;;

    restart)
        echo "Restarting FastOMOP web interface..."
        docker compose restart web
        echo "✓ Restarted"
        docker compose ps
        ;;

    status)
        echo "FastOMOP Status:"
        docker compose ps
        echo ""
        echo "Recent activity:"
        docker compose logs --tail=10 web
        ;;

    logs)
        echo "Showing live logs (Ctrl+C to exit)..."
        docker compose logs -f web
        ;;

    logs-tail)
        echo "Recent logs:"
        docker compose logs --tail=50 web
        ;;

    shell)
        echo "Opening shell in web container..."
        docker compose exec web bash
        ;;

    python)
        echo "Opening Python REPL..."
        docker compose exec web python
        ;;

    test)
        echo "Running interactive CLI mode..."
        docker compose run --rm cli
        ;;

    bootstrap)
        echo "Bootstrapping FastOMOP (initializing prompts and knowledge base)..."
        docker compose run --rm --profile bootstrap bootstrap
        echo "✓ Bootstrap complete"
        ;;

    batch)
        if [ -z "$2" ]; then
            echo "Usage: ./manage.sh batch <queries-file>"
            echo "Example: ./manage.sh batch queries/my_queries.json"
            exit 1
        fi

        QUERIES_FILE="$2"
        if [ ! -f "$QUERIES_FILE" ]; then
            echo "Error: File not found: $QUERIES_FILE"
            exit 1
        fi

        echo "Running batch processing: $QUERIES_FILE"
        mkdir -p queries
        cp "$QUERIES_FILE" queries/queries.json
        docker compose run --rm --profile batch batch
        echo "✓ Batch processing complete"
        ;;

    eval)
        shift  # consume "eval" arg
        DATASET="${DATASET:-medical-cxr-vqa-questions.csv}"
        EVAL_DIR="eval"
        mkdir -p "$EVAL_DIR"

        # Copy dataset to eval dir if it's not already there
        if [ -f "$DATASET" ] && [ ! -f "$EVAL_DIR/$(basename $DATASET)" ]; then
            cp "$DATASET" "$EVAL_DIR/"
        fi

        DATASET_NAME="$(basename $DATASET)"
        echo "Running imaging VQA evaluation: $DATASET_NAME"
        echo "Extra args: $@"

        # Build command: default to direct mode, test split, 100 limit
        docker compose run --rm --profile eval eval \
            python -m agno_fastomop.run_imaging_eval \
            --dataset "/app/eval/$DATASET_NAME" \
            --output "/app/eval/${DATASET_NAME%.csv}_results.json" \
            "$@"
        echo "Results saved to $EVAL_DIR/"
        ;;

    rebuild)
        echo "Rebuilding container..."
        docker compose build --no-cache
        echo "Restarting..."
        docker compose down
        docker compose up -d web
        echo "✓ Rebuild complete"
        docker compose ps
        ;;

    health)
        echo "Health Check:"
        echo ""
        echo "1. Container status:"
        docker compose ps web
        echo ""
        echo "2. Health endpoint:"
        curl -f http://localhost:7777/health 2>/dev/null && echo "✓ Healthy" || echo "✗ Unhealthy"
        echo ""
        echo "3. Ollama connectivity:"
        OLLAMA_HOST=$(grep "^OLLAMA_HOST=" .env | cut -d'=' -f2)
        curl -f "$OLLAMA_HOST/api/tags" > /dev/null 2>&1 && echo "✓ Ollama reachable" || echo "✗ Ollama unreachable"
        ;;

    stats)
        echo "Resource Usage:"
        docker stats fastomop-web --no-stream
        ;;

    backup)
        BACKUP_DIR="./backups"
        mkdir -p "$BACKUP_DIR"
        DATE=$(date +%Y%m%d-%H%M%S)
        BACKUP_FILE="$BACKUP_DIR/fastomop-$DATE.tar.gz"

        echo "Creating backup: $BACKUP_FILE"
        tar -czf "$BACKUP_FILE" \
            config.toml \
            .env \
            data/ \
            queries/ \
            src/agno_fastomop/prompts/ \
            2>/dev/null

        echo "✓ Backup complete: $BACKUP_FILE"
        ls -lh "$BACKUP_FILE"

        # Keep only last 7 backups
        ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null
        ;;

    clean)
        echo "⚠️  This will remove the container and all volumes"
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Cleaning up..."
            docker compose down -v
            echo "✓ Cleaned"
        else
            echo "Cancelled"
        fi
        ;;

    *)
        show_usage
        ;;
esac
