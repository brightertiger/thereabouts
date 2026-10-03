//! Apply a fresh stall budget to every transport read, below HTTP body framing.
use std::time::Duration;
use ureq::{
    Error, Timeout,
    unversioned::transport::{Buffers, ConnectionDetails, Connector, NextTimeout, Transport},
};

#[derive(Debug)]
pub(crate) struct Stall(pub Duration);
#[derive(Debug)]
pub(crate) struct Limited<T>(T, Duration);
impl<T: Transport> Connector<T> for Stall {
    type Out = Limited<T>;
    fn connect(
        &self,
        _: &ConnectionDetails,
        transport: Option<T>,
    ) -> Result<Option<Self::Out>, Error> {
        Ok(transport.map(|value| Limited(value, self.0)))
    }
}
impl<T: Transport> Transport for Limited<T> {
    fn buffers(&mut self) -> &mut dyn Buffers {
        self.0.buffers()
    }
    fn transmit_output(&mut self, amount: usize, timeout: NextTimeout) -> Result<(), Error> {
        self.0.transmit_output(amount, timeout)
    }
    fn await_input(&mut self, timeout: NextTimeout) -> Result<bool, Error> {
        let stalled = NextTimeout {
            after: self.1.into(),
            reason: Timeout::RecvBody,
        };
        self.0.await_input(if timeout.after < stalled.after {
            timeout
        } else {
            stalled
        })
    }
    fn is_open(&mut self) -> bool {
        self.0.is_open()
    }
    fn is_tls(&self) -> bool {
        self.0.is_tls()
    }
}
