#!/bin/bash

set -e

echo "🧹 Docker Cleanup Script"
echo "========================"

echo "📊 Current Docker disk usage:"
docker system df

echo -e "\n⚠️  This will remove:"
echo "  - All stopped containers"
echo "  - All dangling images"
echo "  - All unused networks"
echo "  - All unused volumes"
echo "  - All build cache"

read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo -e "\n🗑️  Removing stopped containers..."
docker container prune -f

echo -e "\n🗑️  Removing dangling images..."
docker image prune -f

echo -e "\n🗑️  Removing unused networks..."
docker network prune -f

echo -e "\n🗑️  Removing unused volumes..."
docker volume prune -f

echo -e "\n🗑️  Removing build cache..."
docker builder prune -af

echo -e "\n🔥 Full system prune (includes all unused images)..."
docker system prune -af --volumes

echo -e "\n✅ Cleanup complete!"
echo "📊 New Docker disk usage:"
docker system df

echo -e "\n💡 Tips to prevent bloat:"
echo "  - Run this script weekly"
echo "  - Use 'docker-compose down -v' to remove volumes when done"
echo "  - Build with --no-cache occasionally to avoid stale cache"
echo "  - Check .dockerignore files are working (build context should be <500MB)"