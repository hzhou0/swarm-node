#!/usr/bin/env python3
import asyncio
import json
import os
import uuid
from pathlib import Path

import coolname
import dotenv
import httpx
import jwt as pyjwt
import typer
from azure.core.exceptions import ResourceExistsError
from azure.data.tables import TableClient

app = typer.Typer()
dotenv.load_dotenv()
table: TableClient = TableClient.from_connection_string(
    os.environ["AZR_CON_STRING"], "registry"
)
try:
    table.create_table()
    typer.secho("Table created", fg=typer.colors.GREEN)
except ResourceExistsError:
    typer.secho("Table exists", fg=typer.colors.CYAN)


def create_entry(folder, id):
    name = coolname.generate_slug()
    while list(table.query_entities(f"PartitionKey eq '{name}'")):
        name = coolname.generate_slug()
    jwt = pyjwt.encode(
        {"alg": "ES256", "sub": name, "_couchdb.roles": [name]},
        os.environ["COUCHDB_JWT_SIGNING_KEY"],
        "ES256",
        headers={"alg": "ES256", "typ": "JWT"},
    )
    # RowKey=id, PartitionKey=name
    table.create_entity({"PartitionKey": name, "RowKey": id, "jwt": jwt})
    credentials = {"name": name, "id": id, "jwt": jwt}
    with open(Path(folder) / ".device.json", "w") as f:
        json.dump(credentials, f)
    print(json.dumps(credentials))


@app.command()
def generate(folder: str = "."):
    create_entry(folder, str(uuid.uuid4()))


@app.command()
def reset(id: str, folder: str = "."):
    lookup = list(table.query_entities(f"RowKey eq '{id}'"))
    if not lookup:
        typer.secho("Invalid device id", fg=typer.colors.RED)
        raise typer.Exit()
    table.delete_entity(lookup[0])
    create_entry(folder, id)


@app.command()
def provision(username: str, password: str, couchdb_url: str = "https://connect.7thletter.dev"):
    prefix = "d_"
    required_dbs = {
        prefix + e["PartitionKey"] for e in table.list_entities(select="PartitionKey")
    }

    async def provision_db():
        tokens = httpx.post(
            f"{couchdb_url}/_session", data={"name": username, "password": password}
        ).cookies
        async with httpx.AsyncClient(base_url=couchdb_url, cookies=tokens) as cl:
            r = await cl.get("/_all_dbs")
            r.raise_for_status()
            databases: set[str] = set(r.json())
            device_dbs: set[str] = {d for d in databases if d.startswith(prefix)}
            delete_dbs = device_dbs - required_dbs
            create_dbs = required_dbs - device_dbs
            typer.secho(delete_dbs, fg=typer.colors.RED)
            typer.secho(create_dbs, fg=typer.colors.GREEN)
            if delete_dbs == create_dbs == set():
                typer.secho("no changes")
                raise typer.Exit()
            typer.confirm(
                f"-{len(delete_dbs)} databases, +{len(create_dbs)} databases",
                abort=True,
            )
            for r in await asyncio.gather(*[cl.delete(f"/{db}") for db in delete_dbs]):
                r.raise_for_status()
            for r in await asyncio.gather(*[cl.put(f"/{db}") for db in create_dbs]):
                r.raise_for_status()
            for r in await asyncio.gather(
                *[
                    cl.put(
                        f"/{db}/_security",
                        json={"members": {"roles": [db.removeprefix(prefix)]}},
                    )
                    for db in create_dbs
                ]
            ):
                r.raise_for_status()

    asyncio.run(provision_db())


if __name__ == "__main__":
    app()
