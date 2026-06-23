# routes/ — Course Route Files

PolarPrism loads every `*.gpx` file in this directory as a course route on
startup. The first route found becomes the active route, and a saved session
may pin a specific one.

## Example data — replace before real use

This directory ships with one **example** route (prefixed `example_` to make
it obvious it is a sample, not your course):

- `example_lake_erie_route.gpx` — the Mills Presidents Trophy Course, a Lake
  Erie race running from Toledo Light past Catawba Buoy and Ballast Island to
  Put-in-Bay.

It lets you see how the Navigation chart overlay, Route tab (bearings,
distances, VMC, ETA), and leg-advance workflow behave before you supply your
own course. **Replace this before relying on the app for real navigation.**

## Using your own routes

1. Delete or overwrite `example_lake_erie_route.gpx` in this directory.
2. Drop one or more `.gpx` files here. Each must contain a `<route>` element
   with `<rtept>` waypoints (lat/lon attributes, optional `<name>`):

   ```xml
   <gpx version="1.1" xmlns="http://www.topografix.net/GPX/1/1">
     <route>
       <name>My Race Course</name>
       <rtept lat="41.7617" lon="-83.3283"><name>START</name></rtept>
       <rtept lat="41.8217" lon="-83.1950"><name>MARK1</name></rtept>
       <rtept lat="41.6633" lon="-82.9733"><name>FINISH</name></rtept>
     </route>
   </gpx>
   ```

3. Restart PolarPrism. Press `R` on the Sailing → Route tab to cycle between
   loaded routes.

See `manual.md` → "Route Files" for full details.