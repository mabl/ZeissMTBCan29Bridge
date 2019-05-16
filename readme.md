About
=====

This code uses the Zeiss Microscope Tool Box (MTB) and its associated 
CAN Server to provide access to a microscope configured in MTB.

That is, if one connects to the COM port, one is presented with a CAN29 compatible
interface, which acts as if it is a microscope. If a true microscope is registered in 
MTB, the commands get forwarded. It does not matter which type of interface is used 
(RS232, USB, Ethernet).

The software has been tested with [micro-manager](http://micro-manager.org) using a 
simulated CAN29 microscope.

Emulation of a microscope
-------------------------

One very convenient feature of MTB is the possibility of simulating a microscope with 
its full set of devices. To this end, MTB connects to the CANServer and simultaneously 
registers a simulation interface at the CAN server.

It is hence possible to interact over CAN with a fully simulated microscope. 
By virtue of this code, the simulated microscope hardware can be exposed as a COM port.

COM loops
---------

Exposing the CAN interface as a real RS232 COM port might not be what you are after.
Using [com0com](http://com0com.sourceforge.net/), a pair of connected virtual COM port
can be created.

Licence etc.
------------

This code has been developed solely against the MTB2011 RDK. 
No confidential information was provided by Zeiss.
Details on CAN messages were extracted from the micro-manager source code.
