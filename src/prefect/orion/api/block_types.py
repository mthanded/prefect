from typing import List, Optional
from uuid import UUID

import sqlalchemy as sa
from fastapi import Body, Depends, HTTPException, Path, Query, status
from packaging.version import Version

from prefect.orion import models, schemas
from prefect.orion.api import dependencies
from prefect.orion.database.dependencies import provide_database_interface
from prefect.orion.database.interface import OrionDBInterface
from prefect.orion.utilities.server import OrionRouter

router = OrionRouter(prefix="/block_types", tags=["Block types"])
LAST_UNPROTECTED_BLOCK_VERSION = Version("0.8.0")


def api_handles_protected_blocks(api_version):
    return False


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_block_type(
    block_type: schemas.actions.BlockTypeCreate,
    db: OrionDBInterface = Depends(provide_database_interface),
) -> schemas.core.BlockType:
    """
    Create a new block type
    """
    # API-created blocks cannot start with the word "Prefect"
    # as it is reserved for system use
    if block_type.name.lower().startswith("prefect"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Block type names beginning with 'Prefect' are reserved.",
        )
    try:
        async with db.session_context(begin_transaction=True) as session:
            created_block_type = await models.block_types.create_block_type(
                session, block_type=block_type
            )
    except sa.exc.IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f'Block type with name "{block_type.name}" already exists',
        )
    return created_block_type


@router.get("/{id}")
async def read_block_type_by_id(
    block_type_id: UUID = Path(..., description="The block type ID", alias="id"),
    db: OrionDBInterface = Depends(provide_database_interface),
) -> schemas.core.BlockType:
    """
    Get a block type by ID.
    """
    async with db.session_context() as session:
        block_type = await models.block_types.read_block_type(
            session=session, block_type_id=block_type_id
        )
    if not block_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Block type not found")
    return block_type


@router.get("/slug/{slug}")
async def read_block_type_by_slug(
    block_type_slug: str = Path(..., description="The block type name", alias="slug"),
    db: OrionDBInterface = Depends(provide_database_interface),
) -> schemas.core.BlockType:
    """
    Get a block type by name.
    """
    async with db.session_context() as session:
        block_type = await models.block_types.read_block_type_by_slug(
            session=session, block_type_slug=block_type_slug
        )
    if not block_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Block type not found")
    return block_type


@router.post("/filter")
async def read_block_types(
    block_types: Optional[schemas.filters.BlockTypeFilter] = None,
    block_schemas: Optional[schemas.filters.BlockSchemaFilter] = None,
    limit: int = dependencies.LimitBody(),
    offset: int = Body(0, ge=0),
    db: OrionDBInterface = Depends(provide_database_interface),
) -> List[schemas.core.BlockType]:
    """
    Gets all block types. Optionally limit return with limit and offset.
    """
    async with db.session_context() as session:
        return await models.block_types.read_block_types(
            session=session,
            limit=limit,
            offset=offset,
            block_type_filter=block_types,
            block_schema_filter=block_schemas,
        )


@router.patch("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_block_type(
    block_type: schemas.actions.BlockTypeUpdate,
    block_type_id: UUID = Path(..., description="The block type ID", alias="id"),
    db: OrionDBInterface = Depends(provide_database_interface),
    api_version=Depends(dependencies.provide_request_api_version),
):
    """
    Update a block type.
    """
    async with db.session_context(begin_transaction=True) as session:
        db_block_type = await models.block_types.read_block_type(
            session=session, block_type_id=block_type_id
        )
        if db_block_type is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Block type not found"
            )
        elif db_block_type.is_protected and api_handles_protected_blocks(api_version):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="protected block types cannot be updated.",
            )
        await models.block_types.update_block_type(
            session=session, block_type=block_type, block_type_id=block_type_id
        )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block_type(
    block_type_id: UUID = Path(..., description="The block type ID", alias="id"),
    db: OrionDBInterface = Depends(provide_database_interface),
    api_version=Depends(dependencies.provide_request_api_version),
):
    async with db.session_context(begin_transaction=True) as session:
        db_block_type = await models.block_types.read_block_type(
            session=session, block_type_id=block_type_id
        )
        if db_block_type is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Block type not found"
            )
        elif db_block_type.is_protected and api_handles_protected_blocks(api_version):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="protected block types cannot be deleted.",
            )
        await models.block_types.delete_block_type(
            session=session, block_type_id=block_type_id
        )


@router.get("/slug/{slug}/block_documents", tags=router.tags + ["Block documents"])
async def read_block_documents_for_block_type(
    db: OrionDBInterface = Depends(provide_database_interface),
    block_type_slug: str = Path(..., description="The block type name", alias="slug"),
    include_secrets: bool = Query(
        False, description="Whether to include sensitive values in the block document."
    ),
) -> List[schemas.core.BlockDocument]:
    async with db.session_context() as session:
        block_type = await models.block_types.read_block_type_by_slug(
            session=session, block_type_slug=block_type_slug
        )
        if not block_type:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Block type not found"
            )
        return await models.block_documents.read_block_documents(
            session=session,
            block_document_filter=schemas.filters.BlockDocumentFilter(
                block_type_id=dict(any_=[block_type.id])
            ),
            include_secrets=include_secrets,
        )


@router.get(
    "/slug/{slug}/block_documents/name/{block_document_name}",
    tags=router.tags + ["Block documents"],
)
async def read_block_document_by_name_for_block_type(
    db: OrionDBInterface = Depends(provide_database_interface),
    block_type_slug: str = Path(..., description="The block type name", alias="slug"),
    block_document_name: str = Path(..., description="The block type name"),
    include_secrets: bool = Query(
        False, description="Whether to include sensitive values in the block document."
    ),
) -> schemas.core.BlockDocument:
    async with db.session_context() as session:
        block_document = await models.block_documents.read_block_document_by_name(
            session=session,
            block_type_slug=block_type_slug,
            name=block_document_name,
            include_secrets=include_secrets,
        )
    if not block_document:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Block document not found"
        )
    return block_document


@router.post("/install_system_block_types")
async def install_system_block_types(
    db: OrionDBInterface = Depends(provide_database_interface),
):
    # Don't begin a transaction. _install_protected_system_blocks will manage
    # the transactions.
    async with db.session_context(begin_transaction=False) as session:
        await models.block_registration._install_protected_system_blocks(session)
