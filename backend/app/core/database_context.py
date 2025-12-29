from typing import Any

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient

type MongoDocument = dict[str, Any]
type DBClient = AsyncMongoClient[MongoDocument]
type Database = AsyncDatabase[MongoDocument]
type Collection = AsyncCollection[MongoDocument]
type Cursor = AsyncCursor[MongoDocument]
type DBSession = AsyncClientSession
