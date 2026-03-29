"""AIYO Server main entry point."""

import os

import typer

cli = typer.Typer(name="aiyo-server", help="AIYO Web Server")


@cli.command()
def run(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8080, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
):
    """Run the AIYO web server."""
    import uvicorn

    # Override with environment variables if set
    host = os.getenv("AIYO_SERVER_HOST", host)
    port = int(os.getenv("AIYO_SERVER_PORT", port))
    reload = os.getenv("AIYO_SERVER_RELOAD", str(reload)).lower() == "true"

    typer.echo(f"Starting AIYO Server on http://{host}:{port}")

    uvicorn.run(
        "aiyo_server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
