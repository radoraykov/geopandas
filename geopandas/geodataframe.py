from collections import OrderedDict
import json
import os

import fiona
import numpy as np
from pandas import DataFrame, Series
from shapely.geometry import mapping

from geopandas import GeoSeries
from geopandas.plotting import plot_dataframe
import geopandas.io


class GeoDataFrame(DataFrame):
    """
    A GeoDataFrame object is a pandas.DataFrame that has a column
    named 'geometry' which is a GeoSeries.
    """
    _prop_attributes = ['crs']

    def __init__(self, *args, **kwargs):
        crs = kwargs.pop('crs', None)
        super(GeoDataFrame, self).__init__(*args, **kwargs)
        self.crs = crs

    @property
    def geometry(self):
        return self['geometry']

    def set_geometry(self, col, drop=True, inplace=False):
        """
        Set the GeoDataFrame geometry using either an existing column or 
        the specified input. By default yields a new object.

        The original geometry column is replaced with the input.

        Parameters
        ----------
        keys : column label or array
        drop : boolean, default True
            Delete column to be used as the new geometry
        inplace : boolean, default False
            Modify the GeoDataFrame in place (do not create a new object)

        Examples
        --------
        >>> df1 = df.set_geometry([Point(0,0), Point(1,1), Point(2,2)])
        >>> df2 = df.set_geometry('geom1')

        Returns
        -------
        geodataframe : GeoDataFrame
        """
        # Most of the code here is taken from DataFrame.set_index()
        if inplace:
            frame = self
        else:
            frame = self.copy()

        to_remove = None
        if isinstance(col, Series):
            level = col.values
        elif isinstance(col, (list, np.ndarray)):
            level = col
        else:
            level = frame[col].values
            if drop:
                to_remove = col

        if to_remove:
            del frame[to_remove]

        frame['geometry'] = level

        if not inplace:
            return frame

    @classmethod
    def from_file(cls, filename, **kwargs):
        """
        Alternate constructor to create a GeoDataFrame from a file.
        
        Example:
            df = geopandas.GeoDataFrame.from_file('nybb.shp')

        Wraps geopandas.read_file(). For additional help, see read_file()

        """
        return geopandas.io.file.read_file(filename, **kwargs)

    @classmethod
    def from_postgis(cls, sql, con, geom_col='geom', crs=None, index_col=None,
                     coerce_float=True, params=None):
        """
        Alternate constructor to create a GeoDataFrame from a sql query
        containing a geometry column.

        Example:
            df = geopandas.GeoDataFrame.from_postgis(con,
                "SELECT geom, highway FROM roads;")

        Wraps geopandas.read_postgis(). For additional help, see read_postgis()

        """
        return geopandas.io.sql.read_postgis(sql, con, geom_col, crs, index_col, 
                     coerce_float, params)


    def to_json(self, **kwargs):
        """Returns a GeoJSON representation of the GeoDataFrame.
        
        The *kwargs* are passed to json.dumps().
        """
        def feature(i, row):
            return {
                'id': str(i),
                'type': 'Feature',
                'properties': {
                    k: v for k, v in row.iteritems() if k != 'geometry'},
                'geometry': mapping(row['geometry']) }

        return json.dumps(
            {'type': 'FeatureCollection',
             'features': [feature(i, row) for i, row in self.iterrows()]},
            **kwargs )
            
    def to_file(self, filename, driver="ESRI Shapefile", **kwargs):
        """
        Write this GeoDataFrame to an OGR data source
        
        A dictionary of supported OGR providers is available via:
        >>> import fiona
        >>> fiona.supported_drivers

        Parameters
        ----------
        filename : string 
            File path or file handle to write to.
        driver : string, default 'ESRI Shapefile'
            The OGR format driver used to write the vector file.

        The *kwargs* are passed to fiona.open and can be used to write 
        to multi-layer data, store data within archives (zip files), etc.
        """
        def convert_type(in_type):
            if in_type == object:
                return 'str'
            return type(np.asscalar(np.zeros(1, in_type))).__name__
            
        def feature(i, row):
            return {
                'id': str(i),
                'type': 'Feature',
                'properties': {
                    k: v for k, v in row.iteritems() if k != 'geometry'},
                'geometry': mapping(row['geometry']) }
        
        properties = OrderedDict([(col, convert_type(_type)) for col, _type 
            in zip(self.columns, self.dtypes) if col!='geometry'])
        # Need to check geom_types before we write to file... 
        # Some (most?) providers expect a single geometry type: 
        # Point, LineString, or Polygon
        geom_types = self['geometry'].geom_type.unique()
        from os.path import commonprefix # To find longest common prefix
        geom_type = commonprefix([g[::-1] for g in geom_types])[::-1]  # Reverse
        if geom_type == '': # No common suffix = mixed geometry types
            raise ValueError("Geometry column cannot contains mutiple "
                             "geometry types when writing to file.")
        schema = {'geometry': geom_type, 'properties': properties}
        filename = os.path.abspath(os.path.expanduser(filename))
        with fiona.open(filename, 'w', driver=driver, crs=self.crs, 
                        schema=schema, **kwargs) as c:
            for i, row in self.iterrows():
                c.write(feature(i, row))

    def to_crs(self, crs=None, epsg=None, inplace=False):
        """Transform geometries to a new coordinate reference system

        This method will transform all points in all objects.  It has
        no notion or projecting entire geometries.  All segments
        joining points are assumed to be lines in the current
        projection, not geodesics.  Objects crossing the dateline (or
        other projection boundary) will have undesirable behavior.
        """
        if inplace:
            df = self
        else:
            df = self.copy()
        geom = df.geometry.to_crs(crs=crs, epsg=epsg)
        df.geometry = geom
        df.crs = geom.crs
        if not inplace:
            return df

    def __getitem__(self, key):
        """
        If the result is a column containing only 'geometry', return a
        GeoSeries. If it's a DataFrame with a 'geometry' column, return a
        GeoDataFrame.
        """
        result = super(GeoDataFrame, self).__getitem__(key)
        if isinstance(key, basestring) and key == 'geometry':
            result.__class__ = GeoSeries
            result.crs = self.crs
        elif isinstance(result, DataFrame) and 'geometry' in result:
            result.__class__ = GeoDataFrame
            result.crs = self.crs
        return result

    #
    # Implement pandas methods
    #

    def _propogate_attributes(self, other):
        """ propogate [sic] attributes from other to self"""
        # NOTE: backported from pandas master (commit 4493bf36)
        for name in self._prop_attributes:
            object.__setattr__(self, name, getattr(other, name, None))
        return self

    def copy(self, deep=True):
        """
        Make a copy of this GeoDataFrame object

        Parameters
        ----------
        deep : boolean, default True
            Make a deep copy, i.e. also copy data

        Returns
        -------
        copy : GeoDataFrame
        """
        # FIXME: this will likely be unnecessary in pandas >= 0.13
        data = self._data
        if deep:
            data = data.copy()
        return GeoDataFrame(data)._propogate_attributes(self)

    def plot(self, *args, **kwargs):
        return plot_dataframe(self, *args, **kwargs)
