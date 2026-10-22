"""This class performs database queries for the site mri_scan_type table"""

from typing_extensions import deprecated


@deprecated('Use `lib.db.models.mri_scan_type.DbMriScanType` instead.')
class MriScanType:
    """
    This class performs database queries for imaging dataset stored in the mri_scan_type table.

    :Example:

        from lib.mri_scan_type import MriScanType
        from lib.database import Database

        # database connection
        db = Database(config.mysql, verbose)
        db.connect()

        mri_scan_type_db_obj = MriScanType(db, verbose)

        ...
    """

    def __init__(self, db, verbose):
        """
        Constructor method for the MriScanType class.

        :param db     : Database class object
         :type db     : object
        :param verbose: whether to be verbose
         :type verbose: bool
        """

        self.db = db
        self.verbose = verbose

    @deprecated('Use `lib.db.queries.mri_scan_type.try_get_mri_scan_type_with_id` instead.')
    def get_scan_type_name_from_id(self, scan_type_id):
        """
        Get a scan type name based on a scan type ID.

        :param scan_type_id: ID of the scan type to look up
         :type scan_type_id: int

        :return: name of the scan type queried
         :rtype: str
        """

        # C-BIG OVERRIDE START
        # Remove when updating to LORIS 27
        results = self.db.pselect(
            query='SELECT Scan_type FROM mri_scan_type WHERE ID = %s',
            args=(scan_type_id,)
        )

        return results[0]['Scan_type'] if results else None
        # C-BIG OVERRIDE END

    @deprecated('Use `lib.db.queries.mri_scan_type.try_get_mri_scan_type_with_name` instead.')
    def get_scan_type_id_from_name(self, scan_type_name):
        """
        Get a scan type ID based on a scan type name.

        :param scan_type_name: name of the scan type to look up
         :type scan_type_name: str

        :return: ID of the scan type queried
         :rtype: int
        """

        # C-BIG OVERRIDE START
        # Remove when updating to LORIS 27
        results = self.db.pselect(
            query='SELECT ID FROM mri_scan_type WHERE Scan_type = %s',
            args=(scan_type_name,)
        )

        return results[0]['ID'] if results else None
        # C-BIG OVERRIDE END
