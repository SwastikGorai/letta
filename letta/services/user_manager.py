from typing import List, Optional, Tuple

from sqlalchemy.exc import NoResultFound

from letta.metadata import AgentModel, AgentSourceMappingModel, SourceModel
from letta.orm.user import User as UserModel
from letta.schemas.user import User as PydanticUser
from letta.schemas.user import UserCreate, UserUpdate
from letta.utils import enforce_types


class UserManager:
    """Manager class to handle business logic related to Users."""

    def __init__(self):
        # Fetching the db_context similarly as in OrganizationManager
        from letta.server.server import db_context

        self.session_maker = db_context

    @enforce_types
    def create_user(self, user_create: UserCreate) -> PydanticUser:
        """Create a new user if it doesn't already exist."""
        with self.session_maker() as session:
            new_user = UserModel(**user_create.model_dump())
            new_user.create(session)
            return new_user.to_pydantic()

    @enforce_types
    def update_user(self, user_update: UserUpdate) -> PydanticUser:
        """Update user details."""
        with self.session_maker() as session:
            # Retrieve the existing user by ID
            existing_user = UserModel.read(db_session=session, identifier=user_update.id)

            # Update only the fields that are provided in UserUpdate
            update_data = user_update.model_dump(exclude_unset=True, exclude_none=True)
            for key, value in update_data.items():
                setattr(existing_user, key, value)

            # Commit the updated user
            existing_user.update(session)
            return existing_user.to_pydantic()

    @enforce_types
    def delete_user_by_id(self, user_id: str):
        """Delete a user and their associated records (agents, sources, mappings)."""
        with self.session_maker() as session:
            # Delete from user table
            user = UserModel.read(db_session=session, identifier=user_id)
            user.delete(session)

            # TODO: Remove this once we have ORM models for the Agent, Source, and AgentSourceMapping
            # Cascade delete for related models: Agent, Source, AgentSourceMapping
            session.query(AgentModel).filter(AgentModel.user_id == user_id).delete()
            session.query(SourceModel).filter(SourceModel.user_id == user_id).delete()
            session.query(AgentSourceMappingModel).filter(AgentSourceMappingModel.user_id == user_id).delete()

            session.commit()

    @enforce_types
    def get_user_by_id(self, user_id: str) -> PydanticUser:
        """Fetch a user by ID."""
        with self.session_maker() as session:
            try:
                user = UserModel.read(db_session=session, identifier=user_id)
                return user.to_pydantic()
            except NoResultFound:
                raise ValueError(f"User with id {user_id} not found.")

    @enforce_types
    def list_all_users(self, cursor: Optional[str] = None, limit: Optional[int] = 50) -> Tuple[Optional[str], List[PydanticUser]]:
        """List users with pagination using cursor (id) and limit."""
        with self.session_maker() as session:
            results = UserModel.list(db_session=session, cursor=cursor, limit=limit)
            return [user.to_pydantic() for user in results]
