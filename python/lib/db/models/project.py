from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base
from lib.db.decorators.int_bool import IntBool


class DbProject(Base):
    __tablename__ = 'Project'

    id                    : Mapped[int]         = mapped_column('ProjectID', primary_key=True)
    name                  : Mapped[str]         = mapped_column('Name')
    alias                 : Mapped[str]         = mapped_column('Alias')
    recruitement_target   : Mapped[int | None]  = mapped_column('recruitmentTarget')
    # C-BIG OVERRIDE START
    # C-BIG specific fields
    guid_required              : Mapped[bool | None] = mapped_column('GUIDRequired', IntBool, default=False)
    pii_storage                : Mapped[str | None]  = mapped_column('PIIStorage')
    imaging_create_visit_label : Mapped[bool | None] = mapped_column('ImagingCreateVisitLabel', IntBool, default=False)
    # C-BIG OVERRIDE END
